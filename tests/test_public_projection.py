from __future__ import annotations

import copy
import contextlib
import io
import json
import unittest
from pathlib import Path

import yaml

from tools import public_projection as projection
from tools.security import PUBLIC_PROJECTION_FINDING_CODES, scan_public_projection


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/public-projection"


class PublicProjectionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = yaml.safe_load((FIXTURE_ROOT / "layout.yaml").read_text(encoding="utf-8"))
        self.request = yaml.safe_load((FIXTURE_ROOT / "request.yaml").read_text(encoding="utf-8"))
        self.approval = yaml.safe_load((FIXTURE_ROOT / "approval.yaml").read_text(encoding="utf-8"))
        self.result = json.loads((FIXTURE_ROOT / "result.json").read_text(encoding="utf-8"))

    def test_closed_schemas_and_synthetic_fixtures_validate(self) -> None:
        expected = {
            "public-project-layout/v1": projection.LAYOUT_SCHEMA_PATH,
            "public-projection-request/v1": projection.REQUEST_SCHEMA_PATH,
            "public-projection-approval/v1": projection.APPROVAL_SCHEMA_PATH,
            "public-projection-result/v1": projection.RESULT_SCHEMA_PATH,
        }
        for contract_version, path in expected.items():
            with self.subTest(contract_version=contract_version):
                schema = projection.load_json(path)
                self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(contract_version, schema["properties"]["contract_version"]["const"])
        self.assertEqual([], projection.validate_layout(self.layout))
        self.assertEqual([], projection.validate_request(self.request))
        self.assertEqual([], projection.validate_approval(self.approval))
        self.assertEqual([], projection.validate_result(self.result))
        expected_hash = projection.request_sha256(self.request)
        self.assertEqual(expected_hash, self.approval["request_sha256"])
        self.assertEqual(expected_hash, self.result["request_sha256"])
        self.assertEqual("READY_FOR_DRY_RUN", projection.projection_policy_status(self.request))

    def test_record_hash_is_canonical_and_drift_is_rejected(self) -> None:
        record = self.request["records"][0]
        files = record["files"]
        self.assertEqual(record["source"]["sha256"], projection.record_file_sha256(files))
        changed = copy.deepcopy(self.request)
        changed["records"][0]["files"][1]["sha256"] = "4" * 64
        errors = projection.validate_request(changed)
        self.assertTrue(any("source.sha256" in error for error in errors))
        self.assertEqual("84ce220804f29e460c2915800dad3534116ba0ba0a1197e672e9604f6b3edbc4", record["source"]["sha256"])

    def test_unknown_clearance_is_blocked_without_becoming_public(self) -> None:
        draft = copy.deepcopy(self.request)
        draft["records"][0]["publication"]["visibility"] = "unknown"
        draft["records"][0]["publication"]["rights_status"] = "unknown"
        self.assertEqual([], projection.validate_request(draft))
        findings = projection.request_policy_findings(draft)
        self.assertEqual("BLOCKED_POLICY", projection.projection_policy_status(draft))
        self.assertGreaterEqual(len(findings), 2)
        self.assertTrue(all(item["code"] == "UNKNOWN_CLEARANCE" for item in findings))

        blocked = copy.deepcopy(self.result)
        blocked["status"] = "BLOCKED_POLICY"
        blocked["findings"] = findings[:1]
        self.assertEqual([], projection.validate_result(blocked))
        self.assertEqual(0, blocked["target"]["mutation_count"])
        self.assertEqual([], blocked["changed_paths"])

    def test_public_security_scan_is_sanitized_and_vocabulary_is_closed(self) -> None:
        findings = scan_public_projection(
            {
                "PRIVATE_RAW": "do not copy",
                "body": "token: ghp_test_secret_value",
                "source_locator": "/Users/example/private.gdoc",
                "provider_url": "https://drive.google.com/drive/folders/internal",
                "direct_identifier": "person@example.test",
            },
            "fixture:public",
        )
        codes = {item["code"] for item in findings}
        self.assertTrue({"FORBIDDEN_CONTENT", "CREDENTIAL", "ABSOLUTE_PATH", "FORBIDDEN_ARTIFACT", "PRIVATE_URL", "INTERNAL_REFERENCE"}.issubset(codes))
        self.assertTrue(codes.issubset(PUBLIC_PROJECTION_FINDING_CODES))
        rendered = json.dumps(findings, ensure_ascii=False, sort_keys=True)
        for forbidden in ("do not copy", "ghp_test_secret_value", "/Users/example", "person@example.test"):
            self.assertNotIn(forbidden, rendered)

    def test_result_rejects_target_mutation_for_blocked_status(self) -> None:
        changed = copy.deepcopy(self.result)
        changed["status"] = "BLOCKED_CONFLICT"
        changed["target"]["mutation_count"] = 1
        changed["changed_paths"] = ["plans/P0001-example-plan/plan.md"]
        errors = projection.validate_result(changed)
        self.assertTrue(any("target mutation" in error for error in errors))

        remote = copy.deepcopy(self.result)
        remote["remote_operations"] = [{"operation": "PUSH"}]
        errors = projection.validate_result(remote)
        self.assertTrue(any("remote_operations" in error for error in errors))

    def test_approval_window_and_cli_are_deterministic_and_read_only(self) -> None:
        invalid = copy.deepcopy(self.approval)
        invalid["expires_at"] = "2026-09-03T00:00:00Z"
        errors = projection.validate_approval(invalid)
        self.assertTrue(any("expires_at" in error for error in errors))

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                0,
                projection.main(["validate", "--layout", str(FIXTURE_ROOT / "layout.yaml"), "--request", str(FIXTURE_ROOT / "request.yaml")]),
            )
        report = json.loads(output.getvalue())
        self.assertEqual("PASSED", report["status"])
        self.assertEqual("READY_FOR_DRY_RUN", report["policy_status"])


if __name__ == "__main__":
    unittest.main()
