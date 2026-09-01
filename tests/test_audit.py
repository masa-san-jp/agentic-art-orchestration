from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

import yaml

from tools.audit import EXPECTED_BOUNDARIES, build_audit, render_markdown


ROOT = Path(__file__).resolve().parents[1]


def manifest() -> dict:
    return {
        "repositories": [
            {"id": "self-model", "observed_commit": "1" * 40, "export_contract": "normalized-research-signal/v1"},
            {"id": "art-history", "observed_commit": "2" * 40, "export_contract": "normalized-research-signal/v1"},
            {"id": "marketing-trends", "observed_commit": "3" * 40, "export_contract": "normalized-research-signal/v1"},
            {"id": "agentic-art-research", "observed_commit": "4" * 40, "import_contract": "normalized-research-signal/v1"},
            {"id": "agentic-art-production", "observed_commit": "5" * 40, "exchange_contracts": {"imports": ["production-handoff/v1"], "exports": ["production-result/v1"]}},
        ]
    }


def snapshot() -> dict:
    return {
        "captured_at": "2026-08-11T06:47:52Z",
        "repositories": [
            {"id": "self-model", "manifest_observed_commit": "1" * 40, "contract": {"version": "normalized-research-signal/v1"}},
            {"id": "art-history", "manifest_observed_commit": "2" * 40, "contract": {"version": "normalized-research-signal/v1"}},
            {"id": "marketing-trends", "manifest_observed_commit": "3" * 40, "contract": {"version": "normalized-research-signal/v1"}},
            {"id": "agentic-art-research", "manifest_observed_commit": "4" * 40, "contract": {"version": "normalized-research-signal/v1"}},
            {"id": "agentic-art-production", "manifest_observed_commit": "5" * 40, "contract": {"direction": "exchange", "imports": ["production-handoff/v1"], "exports": ["production-result/v1"]}},
        ]
    }


def signals() -> list[dict]:
    return [
        json.loads((ROOT / "tests/fixtures/signal/valid_self.json").read_text(encoding="utf-8")),
        json.loads((ROOT / "tests/fixtures/signal/valid_art_history.json").read_text(encoding="utf-8")),
        json.loads((ROOT / "tests/fixtures/signal/valid_marketing.json").read_text(encoding="utf-8")),
    ]


def requirements() -> list[dict]:
    return [{"id": "r1", "signal_ids": [signal["signal_id"] for signal in signals()]}]


def queue() -> dict:
    return {"updated_at": "2026-08-11T16:00:00+09:00", "tasks": [{"id": "AUDIT-001", "status": "READY"}]}


def state() -> dict:
    return {"updated_at": "2026-08-11T16:01:00+09:00", "blocked": []}


class AuditTests(unittest.TestCase):
    def test_clean_fixture_reports_all_audit_dimensions_without_blocking(self):
        tested = {boundary: True for boundary in EXPECTED_BOUNDARIES}
        result = build_audit(manifest(), snapshot(), queue(), state(), signals(), requirements(), tested)

        self.assertEqual("CLEAN", result["status"])
        self.assertFalse(result["blocking"])
        self.assertEqual(0, result["summary"]["finding_count"])

    def test_stale_pin_and_schema_drift_are_findings(self):
        altered_manifest = manifest()
        altered_manifest["repositories"][0]["observed_commit"] = "9" * 40
        altered_manifest["repositories"][1]["export_contract"] = "normalized-research-signal/v2"
        tested = {boundary: True for boundary in EXPECTED_BOUNDARIES}
        result = build_audit(altered_manifest, snapshot(), queue(), state(), signals(), requirements(), tested)
        codes = {finding["code"] for finding in result["findings"]}

        self.assertIn("stale-pin", codes)
        self.assertIn("schema-drift", codes)
        self.assertFalse(result["blocking"])

    def test_orphan_freshness_consent_and_duplicate_findings_are_preserved(self):
        altered = signals()
        altered[2]["freshness"]["status"] = "stale"
        altered[0]["domain"]["self_model"]["export_permitted"] = False
        altered.append(copy.deepcopy(altered[0]))
        altered[1]["signal_id"] = "orphan-signal"
        tested = {boundary: True for boundary in EXPECTED_BOUNDARIES}
        result = build_audit(manifest(), snapshot(), queue(), state(), altered, requirements(), tested)
        codes = {finding["code"] for finding in result["findings"]}

        self.assertIn("duplicate", codes)
        self.assertIn("freshness", codes)
        self.assertIn("consent", codes)
        self.assertIn("orphan", codes)

    def test_duplicate_task_and_untested_boundary_are_reported(self):
        altered_queue = queue()
        altered_queue["tasks"].append({"id": "AUDIT-001", "status": "READY"})
        tested = {boundary: True for boundary in EXPECTED_BOUNDARIES}
        tested["project-sync"] = False
        result = build_audit(manifest(), snapshot(), altered_queue, state(), signals(), requirements(), tested)

        self.assertTrue(any(finding["code"] == "duplicate" for finding in result["findings"]))
        self.assertTrue(any(finding["code"] == "untested-boundary" for finding in result["findings"]))

    def test_audit_is_deterministic_and_markdown_is_rendered(self):
        tested = {boundary: True for boundary in EXPECTED_BOUNDARIES}
        inputs = [manifest(), snapshot(), queue(), state(), signals(), requirements(), tested]
        before = copy.deepcopy(inputs)
        first = build_audit(*inputs)
        second = build_audit(*inputs)

        self.assertEqual(first, second)
        self.assertEqual(render_markdown(first), render_markdown(second))
        self.assertEqual(before, inputs)

    def test_parent_ahead_of_origin_is_a_named_non_blocking_finding(self):
        tested = {boundary: True for boundary in EXPECTED_BOUNDARIES}
        parent_git = {
            "status": "AHEAD",
            "branch": "agent/issues-38-41-pipeline",
            "head": "a" * 40,
            "upstream": "origin/agent/issues-38-41-pipeline",
            "ahead": 4,
            "behind": 0,
            "observed_via": "local_tracking_ref",
            "network_status": "UNKNOWN",
            "unknowns": ["remote_head_not_fetched"],
            "remote_operations": [],
        }
        result = build_audit(manifest(), snapshot(), queue(), state(), signals(), requirements(), tested, parent_git)

        finding = next(item for item in result["findings"] if item["code"] == "PARENT_SSOT_UNPUSHED")
        self.assertEqual("AHEAD", finding["observed"]["status"])
        self.assertEqual("UNKNOWN", finding["observed"]["network_status"])
        self.assertFalse(result["blocking"])
        self.assertEqual(0, result["summary"]["error_count"])

    def test_parent_network_unknown_is_preserved_without_false_clean_result(self):
        tested = {boundary: True for boundary in EXPECTED_BOUNDARIES}
        parent_git = {
            "status": "UNKNOWN",
            "branch": "agent/issues-38-41-pipeline",
            "head": "b" * 40,
            "upstream": None,
            "ahead": None,
            "behind": None,
            "observed_via": "local_tracking_ref",
            "network_status": "UNKNOWN",
            "unknowns": ["network_unavailable"],
            "remote_operations": [],
        }
        result = build_audit(manifest(), snapshot(), queue(), state(), signals(), requirements(), tested, parent_git)

        finding = next(item for item in result["findings"] if item["code"] == "PARENT_SSOT_UNPUSHED")
        self.assertEqual("UNKNOWN", finding["observed"]["status"])
        self.assertEqual(["network_unavailable"], finding["observed"]["unknowns"])
        self.assertIsNone(finding["observed"]["ahead"])
        self.assertFalse(result["blocking"])


if __name__ == "__main__":
    unittest.main()
