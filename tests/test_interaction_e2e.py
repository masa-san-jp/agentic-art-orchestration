from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from tools.interaction_e2e import run_interaction_e2e
from tools.validate import load_yaml, validate_interaction_e2e


ROOT = Path(__file__).resolve().parents[1]


class InteractionE2ETests(unittest.TestCase):
    def test_networkless_scenario_connects_all_frontstage_and_backstage_stages(self):
        result = run_interaction_e2e("INTERACTION-E2E-001:test-clean")

        self.assertEqual("interaction-e2e/v1", result["contract_version"])
        self.assertEqual("disabled", result["network"])
        self.assertEqual("COMPLETE_WITH_GAPS", result["retrieval"]["status"])
        self.assertEqual("CREATE", result["artifact"]["operation"])
        self.assertEqual(2, len(result["feedback"]["feedback_ids"]))
        self.assertIn("feedback:interaction-001:001", result["feedback"]["inferred_feedback_ids"])
        self.assertFalse(result["feedback"]["promoted_to_user_fact"])
        self.assertEqual({"ROUTED", "TRIAGE"}, set(result["routing"]["statuses"]))
        self.assertEqual({"DRAFT_PR_READY", "TRIAGE"}, set(result["improvement"]["statuses"]))
        self.assertEqual("ASYNC_AUDIT", result["audit"]["lane"])
        self.assertTrue(all(result["acceptance"].values()))
        self.assertEqual([], result["remote_operations"])
        self.assertEqual([], validate_interaction_e2e(result, load_yaml(ROOT / "config/repositories.yaml")))

    def test_artifact_is_reference_only_and_recovery_preserves_execution(self):
        result = run_interaction_e2e("INTERACTION-E2E-001:test-artifact-recovery")

        artifact = result["artifact"]
        self.assertTrue(artifact["provider_file_id"].startswith("drive-file-"))
        payload = json.dumps(result)
        self.assertNotIn('"content":', payload)
        self.assertTrue(result["recovery"]["lease_expiry_recovered"])
        self.assertTrue(result["recovery"]["process_interruption_recovered"])
        self.assertTrue(result["recovery"]["execution_id_preserved"])

    def test_result_is_deterministic_and_inputs_are_not_exposed(self):
        first = run_interaction_e2e("INTERACTION-E2E-001:test-deterministic")
        second = run_interaction_e2e("INTERACTION-E2E-001:test-deterministic")

        self.assertEqual(first, second)
        payload = json.dumps(first)
        self.assertNotIn('"raw_query":', payload)
        self.assertNotIn('"conversation":', payload)

    def test_validator_rejects_remote_mutation_and_incomplete_acceptance(self):
        result = run_interaction_e2e("INTERACTION-E2E-001:test-validator")
        altered = copy.deepcopy(result)
        altered["remote_operations"] = [{"operation": "CREATE_PR"}]
        errors = validate_interaction_e2e(altered, load_yaml(ROOT / "config/repositories.yaml"))
        self.assertTrue(any("remote_operations" in error for error in errors))

        altered = copy.deepcopy(result)
        altered["acceptance"]["audit_independent"] = False
        errors = validate_interaction_e2e(altered, load_yaml(ROOT / "config/repositories.yaml"))
        self.assertTrue(any("acceptance" in error for error in errors))

    def test_schema_declares_networkless_create_only_and_no_remote_operations(self):
        schema = json.loads((ROOT / "schemas/interaction-e2e.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("interaction-e2e/v1", schema["properties"]["contract_version"]["const"])
        self.assertEqual("disabled", schema["properties"]["network"]["const"])
        self.assertEqual("CREATE_ONLY", schema["properties"]["user_artifact_policy"]["const"])
        self.assertEqual([], schema["properties"]["remote_operations"]["const"])


if __name__ == "__main__":
    unittest.main()
