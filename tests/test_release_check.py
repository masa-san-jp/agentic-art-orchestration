from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.release_check import (
    ReleaseCheckError,
    _e2e_check,
    _history_forbidden_findings,
    _interaction_e2e_check,
    _v12_child_quality_gate_check,
    _v12_e2e_check,
    validate_request,
)


class ReleaseCheckTests(unittest.TestCase):
    def test_request_requires_declared_version_and_positive_runs(self):
        validate_request("1.0.0", 3)
        validate_request("1.1.0", 3)
        validate_request("1.2.0", 3)
        validate_request("1.2.1", 3)
        with self.assertRaisesRegex(ReleaseCheckError, "only versions 1.0.0, 1.1.0, 1.2.0, and 1.2.1"):
            validate_request("2.0.0", 3)
        with self.assertRaisesRegex(ReleaseCheckError, "runs must be positive"):
            validate_request("1.0.0", 0)

    def test_history_scan_returns_sanitized_observations(self):
        result = _history_forbidden_findings()
        self.assertEqual("PASSED", result["status"])
        self.assertEqual(0, result["finding_count"])
        self.assertTrue(result["commit_count"] >= 1)
        self.assertNotIn("password", str(result))

    def test_e2e_check_has_deterministic_run_evidence(self):
        result = _e2e_check(1)
        self.assertEqual("offline-e2e", result["id"])
        self.assertEqual(1, result["runs"])
        self.assertTrue(result["deterministic"])
        self.assertTrue(result["clean_complete"])
        self.assertEqual([9], result["failure_case_counts"])

    def test_interaction_e2e_check_proves_v11_boundaries(self):
        result = _interaction_e2e_check(1)
        self.assertEqual("interaction-e2e", result["id"])
        self.assertEqual(1, result["runs"])
        self.assertTrue(result["deterministic"])
        self.assertTrue(result["acceptance_passed"])
        self.assertTrue(result["no_remote_mutation"])

    def test_v12_check_blocks_when_child_gate_is_not_passed(self):
        result = _v12_e2e_check(1)
        self.assertEqual("v1.2-e2e", result["id"])
        self.assertTrue(result["deterministic"])
        self.assertFalse(result["child_gates_passed"])

    def test_v12_child_gate_report_is_a_blocking_release_check(self):
        with tempfile.TemporaryDirectory() as temporary_name:
            report_path = Path(temporary_name) / "child-quality-gates.json"
            report_path.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "status": "BLOCKED",
                                "gates": [{"status": "BLOCKED"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = _v12_child_quality_gate_check(report_path)
        self.assertEqual("v1.2-child-quality-gates-result", result["id"])
        self.assertEqual("FAILED", result["status"])
        self.assertIn("BLOCKED", result["repository_statuses"])


if __name__ == "__main__":
    unittest.main()
