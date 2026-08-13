from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.initial_operations_e2e import InitialOperationsE2EError, run_initial_operations_e2e
from tools.validate import load_json, validate_initial_operations_e2e


ROOT = Path(__file__).resolve().parents[1]


class InitialOperationsE2ETests(unittest.TestCase):
    def _run(self, run_id: str = "INITIAL-OPS-E2E-001:test-contract"):
        return run_initial_operations_e2e(
            run_id,
            offline_fixture=True,
            fixture_root=Path(tempfile.mkdtemp(prefix="initial-ops-e2e-test-")),
        )

    def test_networkless_flow_proves_startup_pinned_answer_drive_replay_and_issue_reuse(self):
        result = self._run()

        self.assertEqual("initial-operations-e2e/v1", result["contract_version"])
        self.assertEqual("disabled", result["network"])
        self.assertEqual(9, result["startup"]["ordered_step_count"])
        self.assertTrue(all("@" in source["repository_at_commit"] for source in result["retrieval"]["sources"]))
        self.assertEqual("CREATED", result["drive"]["create_status"])
        self.assertEqual("REPLAYED", result["drive"]["replay_status"])
        self.assertEqual(1, result["drive"]["provider_file_count"])
        self.assertEqual("CREATED", result["issue"]["create"]["status"])
        self.assertEqual("REUSED", result["issue"]["reuse"]["status"])
        self.assertEqual([], result["remote_operations"])
        self.assertTrue(all(result["acceptance"].values()))
        self.assertEqual([], validate_initial_operations_e2e(result))

    def test_networkless_result_is_deterministic_and_reference_only(self):
        first = self._run("INITIAL-OPS-E2E-001:test-deterministic")
        second = self._run("INITIAL-OPS-E2E-001:test-deterministic")

        self.assertEqual(first, second)
        payload = json.dumps(first)
        self.assertNotIn('"content"', payload)
        self.assertNotIn('"conversation"', payload)
        self.assertNotIn('"credential"', payload)
        self.assertFalse(first["privacy"]["drive_content_stored"])

    def test_non_offline_path_is_fail_closed(self):
        with self.assertRaisesRegex(InitialOperationsE2EError, "offline-fixture"):
            run_initial_operations_e2e(
                "INITIAL-OPS-E2E-001:test-live-gate",
                offline_fixture=False,
                fixture_root=Path(tempfile.mkdtemp(prefix="initial-ops-live-refusal-")),
            )

    def test_validator_rejects_remote_operation_or_lost_provenance(self):
        result = self._run("INITIAL-OPS-E2E-001:test-validator")

        altered = copy.deepcopy(result)
        altered["remote_operations"] = [{"operation": "CREATE", "system": "google-drive"}]
        errors = validate_initial_operations_e2e(altered)
        self.assertTrue(any("remote operations" in error for error in errors))

        altered = copy.deepcopy(result)
        altered["retrieval"]["sources"][0]["repository_at_commit"] = "art-history"
        errors = validate_initial_operations_e2e(altered)
        self.assertTrue(any("repository@commit" in error for error in errors))

    def test_schema_declares_networkless_live_gate_and_create_only_operations(self):
        schema = load_json(ROOT / "schemas/initial-operations-e2e.schema.json")

        self.assertEqual("initial-operations-e2e/v1", schema["properties"]["contract_version"]["const"])
        self.assertEqual("disabled", schema["properties"]["network"]["const"])
        self.assertEqual([], schema["properties"]["remote_operations"]["const"])
        self.assertEqual("NOT_REQUESTED", schema["$defs"]["live_gate"]["properties"]["status"]["const"])
        self.assertEqual([], schema["$defs"]["drive"]["properties"]["forbidden_operations"]["const"])
        self.assertEqual([], schema["$defs"]["issue"]["properties"]["forbidden_operations"]["const"])


if __name__ == "__main__":
    unittest.main()
