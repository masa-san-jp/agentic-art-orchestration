from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release_check import (
    ReleaseCheckError,
    _e2e_check,
    _history_forbidden_findings,
    _active_python,
    _initial_operations_e2e_check,
    _interaction_e2e_check,
    _production_exchange_check,
    _sandbox_live_evidence_check,
    _v12_child_quality_gate_check,
    _v12_e2e_check,
    validate_request,
)


class ReleaseCheckTests(unittest.TestCase):
    def test_active_python_uses_virtualenv_interpreter_when_available(self):
        active = Path(_active_python())
        self.assertTrue(active.is_file())
        if Path(sys.prefix) != Path(sys.base_prefix):
            self.assertEqual(Path(sys.prefix), active.parent.parent)

    def test_request_requires_declared_version_and_positive_runs(self):
        validate_request("1.0.0", 3)
        validate_request("1.1.0", 3)
        validate_request("1.2.0", 3)
        validate_request("1.2.1", 3)
        validate_request("1.3.0", 3)
        validate_request("1.4.0", 3)
        with self.assertRaisesRegex(ReleaseCheckError, "only versions 1.0.0, 1.1.0, 1.2.0, 1.2.1, 1.3.0, and 1.4.0"):
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

    def test_initial_operations_check_proves_three_deterministic_networkless_runs(self):
        result = _initial_operations_e2e_check(3)
        self.assertEqual("initial-operations-e2e", result["id"])
        self.assertTrue(result["deterministic"])
        self.assertTrue(result["acceptance_passed"])
        self.assertTrue(result["drive_idempotent"])
        self.assertTrue(result["issue_idempotent"])
        self.assertTrue(result["live_gate_closed"])
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

    def test_production_check_requires_three_stable_exchange_reports_and_all_child_gates(self):
        exchange = {
            "scenarios": [
                {"scenario_id": "clean", "status": "PASSED", "terminal_status": "COMPLETE"},
                {"scenario_id": "tamper", "status": "FAILED", "terminal_status": "FAILED"},
                {"scenario_id": "stale", "status": "BLOCKED", "terminal_status": "BLOCKED"},
                {"scenario_id": "incompatible", "status": "FAILED", "terminal_status": "FAILED"},
                {"scenario_id": "dirty-source", "status": "BLOCKED", "terminal_status": "BLOCKED"},
                {"scenario_id": "replay", "status": "PASSED", "terminal_status": "REPLAYED"},
            ],
            "normal_exchange": {
                "status": "PASSED",
                "external_validation_required": True,
                "research_result_dry_run": True,
            },
            "remote_operations": [],
            "child_mutations": [],
        }
        child_results = []
        for index in range(5):
            commit = f"{index + 1:040x}"
            child_results.append(
                {
                    "status": "PASSED",
                    "workspace_state": "MATCHED",
                    "workspace_commit": commit,
                    "observed_commit": commit,
                    "execution_mode": "immutable-archive",
                    "gates": [{"status": "PASSED"}] * (2 if index == 4 else 3),
                }
            )
        with patch("tools.release_check.run_exchange_e2e", return_value=exchange), patch(
            "tools.release_check.run_child_quality_gates",
            return_value={"results": child_results},
        ), patch("tools.release_check._git", return_value=""):
            result = _production_exchange_check(3, Path("/tmp/verified-child-workspace"), "python3")
        self.assertEqual("PASSED", result["status"])
        self.assertTrue(result["deterministic"])
        self.assertTrue(result["child_gates_passed"])
        self.assertEqual(3, len(result["report_sha256"]))

    def test_sandbox_live_evidence_is_accepted_only_after_create_and_reuse(self):
        from tools.github_sandbox_live_check import FixtureProvider, run_check

        with tempfile.TemporaryDirectory() as temporary_name:
            evidence_path = Path(temporary_name) / "github-sandbox-live-evidence.json"
            with patch.dict("os.environ", {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/dedicated-sandbox"}, clear=False):
                evidence = run_check(mode="live", confirm_live=True, provider=FixtureProvider())
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            result = _sandbox_live_evidence_check(evidence_path)
        self.assertEqual("PASSED", result["status"])
        self.assertEqual("PASSED", result["github_issue_create_reuse"])
        self.assertEqual(["READ", "CREATE", "READ", "REUSE"], [item["operation"] for item in result["remote_operations"]])


if __name__ == "__main__":
    unittest.main()
