from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.child_quality_gates import sha256_hex
from tools.v12_e2e import _deterministic_view, run_v12_e2e
from tools.validate import load_yaml, validate_v12_e2e


ROOT = Path(__file__).resolve().parents[1]


class V12E2ETests(unittest.TestCase):
    def test_pipeline_connects_all_v12_stages_and_preserves_v11_boundary(self):
        result = run_v12_e2e("V12-E2E-001:test-clean")
        self.assertEqual("v12-e2e/v1", result["contract_version"])
        self.assertEqual("disabled", result["network"])
        self.assertEqual(3, result["pipeline"]["signal_count"])
        self.assertEqual(1, result["pipeline"]["candidate_count"])
        self.assertEqual(1, result["pipeline"]["selection"]["selected_count"])
        self.assertEqual("research-provenance/v1", result["pipeline"]["provenance"]["contract_version"])
        self.assertEqual(5, result["child_quality_gates"]["repository_count"])
        self.assertEqual("interaction-e2e/v1", result["v11_regression"]["interaction_contract"])
        self.assertTrue(all(result["acceptance"].values()))
        self.assertEqual([], result["remote_operations"])
        self.assertEqual([], validate_v12_e2e(result, load_yaml(ROOT / "config/repositories.yaml")))

    def test_repeated_pipeline_is_deterministic_and_does_not_expose_raw_content(self):
        first = run_v12_e2e("V12-E2E-001:test-deterministic")
        second = run_v12_e2e("V12-E2E-001:test-deterministic")
        self.assertEqual(first, second)
        payload = json.dumps(first, ensure_ascii=False)
        self.assertNotIn('"statement":', payload)
        self.assertNotIn('"conversation":', payload)
        self.assertNotIn('"content":', payload)

    def test_child_gate_blocked_state_is_preserved(self):
        result = run_v12_e2e("V12-E2E-001:test-child-gates")
        self.assertIn("BLOCKED", result["child_quality_gates"]["statuses"])
        self.assertIn("NOT_RUN", result["child_quality_gates"]["execution_modes"])
        self.assertIn("STALE", result["child_quality_gates"]["workspace_states"])
        self.assertTrue(result["acceptance"]["child_gates_observed"])

    def test_validator_rejects_incomplete_or_remote_mutation(self):
        result = run_v12_e2e("V12-E2E-001:test-validator")
        altered = copy.deepcopy(result)
        altered["remote_operations"] = [{"operation": "MERGE"}]
        errors = validate_v12_e2e(altered, load_yaml(ROOT / "config/repositories.yaml"))
        self.assertTrue(any("remote_operations" in error for error in errors))

        altered = copy.deepcopy(result)
        altered["pipeline"]["provenance"]["proposition_count"] = 2
        errors = validate_v12_e2e(altered, load_yaml(ROOT / "config/repositories.yaml"))
        self.assertTrue(any("provenance count" in error for error in errors))

    def test_schema_is_versioned_and_networkless(self):
        schema = json.loads((ROOT / "schemas/v12-e2e.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("v12-e2e/v1", schema["properties"]["contract_version"]["const"])
        self.assertEqual("disabled", schema["properties"]["network"]["const"])
        self.assertEqual([], schema["properties"]["remote_operations"]["const"])

    def test_deterministic_view_ignores_only_runtime_gate_output(self):
        first = {"duration_ms": 1, "output_sha256": "a", "nested": [{"status": "PASSED"}]}
        second = {"duration_ms": 99, "output_sha256": "b", "nested": [{"status": "PASSED"}]}
        self.assertEqual(_deterministic_view(first), _deterministic_view(second))

    def test_validated_child_gate_evidence_can_be_reused_without_rerunning_gates(self):
        child = {
            "contract_version": "child-quality-gates/v1",
            "run_id": "fixture-child-gates",
            "manifest_hash": sha256_hex(load_yaml(ROOT / "config/repositories.yaml")),
            "repository_count": 5,
            "results": [
                {
                    "repository": repository["id"],
                    "observed_commit": repository["observed_commit"],
                    "workspace_commit": repository["observed_commit"],
                    "workspace_state": "MATCHED",
                    "execution_mode": "immutable-archive",
                    "quality_gate_hash": sha256_hex(repository["quality_gates"]),
                    "status": "PASSED",
                    "gates": [
                        {
                            "command": command,
                            "status": "PASSED",
                            "exit_code": 0,
                            "duration_ms": 0,
                            "output_redacted": "",
                            "output_truncated": False,
                            "output_sha256": "0" * 64,
                        }
                        for command in repository["quality_gates"]
                    ],
                }
                for repository in load_yaml(ROOT / "config/repositories.yaml")["repositories"]
            ],
        }
        with patch("tools.v12_e2e.run_child_quality_gates", side_effect=AssertionError("gate rerun")):
            result = run_v12_e2e("V12-E2E-001:test-reuse", child_quality_gates=child)
        self.assertEqual(["PASSED"], result["child_quality_gates"]["statuses"])

    def test_reused_child_gate_evidence_must_match_manifest(self):
        child = {"contract_version": "child-quality-gates/v1", "manifest_hash": "0" * 64, "results": []}
        with self.assertRaisesRegex(RuntimeError, "provided child quality gate evidence is invalid"):
            run_v12_e2e("V12-E2E-001:test-reuse-mismatch", child_quality_gates=child)


if __name__ == "__main__":
    unittest.main()
