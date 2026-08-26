from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.viewer_response_gate import ViewerResponseGateError, assess_and_gate, assess_records, wilson95


COMMIT = "0123456789abcdef0123456789abcdef01234567"


def record(*, source_kind: str = "measured", sample_size: int = 5, passed: int = 5, failed: int = 0, record_id: str = "VRR-001", evidence: str = "production-result:PR001#AT001") -> dict:
    value = {
        "record_id": record_id,
        "work_id": "production/work-1",
        "requirement_id": "RQ001",
        "source_kind": source_kind,
        "presentation_mode": "gallery",
        "requirement_tags": ["clarity"],
        "sample_size": sample_size if source_kind == "measured" else 0,
        "outcome_counts": {"pass": passed if source_kind == "measured" else 0, "fail": failed if source_kind == "measured" else 0, "unknown": (sample_size - passed - failed) if source_kind == "measured" else 0},
        "evidence_refs": [evidence],
        "certainty": "high",
        "consent_scope": "aggregate-only",
        "source_commit": COMMIT,
        "observed_at": "2026-08-26T12:00:00+09:00",
    }
    payload = [value["work_id"], value["requirement_id"], value["presentation_mode"], sorted(value["evidence_refs"])]
    value["dedup_key"] = "sha256:" + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return value


class ViewerResponseGateTests(unittest.TestCase):
    def test_wilson_and_supported(self) -> None:
        self.assertEqual({"level": 0.95, "lower": 0.565518, "upper": 1.0}, wilson95(5, 5))
        assessment = assess_records([record()], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])
        self.assertEqual("UNKNOWN", assessment["status"])
        supported = record(sample_size=20, passed=20, record_id="VRR-002")
        assessment = assess_records([supported], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])
        self.assertEqual("SUPPORTED", assessment["status"])
        self.assertFalse(assessment["review_required"])

    def test_contradicted_unknown_and_no_match_are_conservative(self) -> None:
        contradicted = record(sample_size=20, passed=0, failed=20)
        result = assess_records([contradicted], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])
        self.assertEqual("CONTRADICTED", result["status"])
        self.assertEqual("BLIND_OR_FRAME", result["review_kind"])
        result = assess_records([contradicted], work_id="production/other", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])
        self.assertEqual("UNKNOWN", result["status"])
        self.assertEqual(0, result["measured_sample_size"])

    def test_external_support_and_measured_external_conflict(self) -> None:
        first = record(source_kind="external", record_id="VRR-EXT-1", evidence="doi:10.1/one")
        second = record(source_kind="external", record_id="VRR-EXT-2", evidence="doi:10.1/two")
        result = assess_records([first, second], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])
        self.assertEqual("EXTERNALLY_SUPPORTED", result["status"])
        self.assertTrue(result["review_required"])
        measured = record(sample_size=20, passed=20, record_id="VRR-MEASURED")
        result = assess_records([measured, first, second], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])
        self.assertEqual("SUPPORTED", result["status"])
        self.assertTrue(result["conflict"])

    def test_exact_mode_and_tag_matching(self) -> None:
        value = record(sample_size=20, passed=20)
        self.assertEqual("UNKNOWN", assess_records([value], work_id="production/work-1", requirement_id="RQ001", presentation_mode="projection", requirement_tags=["clarity"])["status"])
        self.assertEqual("UNKNOWN", assess_records([value], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["accessibility"])["status"])

    def test_closed_privacy_and_aggregate_boundaries(self) -> None:
        invalid = record()
        invalid["free_text"] = "not allowed"
        with self.assertRaisesRegex(ViewerResponseGateError, "forbidden"):
            assess_records([invalid], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])
        invalid = record(source_kind="external")
        invalid["sample_size"] = 1
        invalid["outcome_counts"] = {"pass": 1, "fail": 0, "unknown": 0}
        with self.assertRaisesRegex(ViewerResponseGateError, "external evidence"):
            assess_records([invalid], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])
        invalid = record()
        invalid.pop("certainty")
        with self.assertRaisesRegex(ViewerResponseGateError, "complete viewer-response-record"):
            assess_records([invalid], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])
        invalid = record()
        invalid["dedup_key"] = "sha256:" + "a" * 64
        with self.assertRaisesRegex(ViewerResponseGateError, "dedup_key"):
            assess_records([invalid], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])

    def test_plan_requires_blind_or_frame_review_for_unknown_family(self) -> None:
        plan = {
            "requirements": [{"id": "RQ001", "viewer_facing": True, "acceptance_test_ids": ["AT001"]}],
            "acceptance_tests": [{"id": "AT001", "method": "ordinary review", "pass_condition": "requirement is met"}],
        }
        with self.assertRaisesRegex(ViewerResponseGateError, "PLANNING_VIEWER_REVIEW_REQUIRED"):
            assess_and_gate([record()], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"], plan=plan)
        plan["acceptance_tests"][0]["method"] = "blind frame review"
        self.assertEqual("UNKNOWN", assess_and_gate([record()], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"], plan=plan)["status"])

    def test_assessment_is_deterministic_and_schema_closed(self) -> None:
        value = record(sample_size=20, passed=19, failed=1)
        one = assess_records([value], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])
        two = assess_records([copy.deepcopy(value)], work_id="production/work-1", requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["clarity"])
        self.assertEqual(one, two)
        self.assertNotIn("statement", one)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            self.assertEqual(1, len(path.read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    unittest.main()
