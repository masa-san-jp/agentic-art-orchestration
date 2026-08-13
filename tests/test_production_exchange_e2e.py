from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.production_exchange import validate_exchange_e2e


class ProductionExchangeE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = {
            "contract_version": "production-exchange-e2e/v1",
            "run_id": "PRODUCTION-E2E-001:test",
            "network": "disabled",
            "status": "PASSED",
            "normal_exchange": {
                "status": "PASSED",
                "evidence_sha256": "sha256:" + "a" * 64,
                "stage_count": 8,
                "result_statuses": ["EXTERNAL_VALIDATION_REQUIRED", "NOT_RUN"],
                "external_validation_required": True,
                "research_result_dry_run": True,
            },
            "scenarios": [
                {"scenario_id": "clean", "status": "PASSED", "terminal_status": "COMPLETE", "reason_code": "CLEAN_EXCHANGE"},
                {"scenario_id": "tamper", "status": "FAILED", "terminal_status": "FAILED", "reason_code": "TAMPER_DETECTED"},
                {"scenario_id": "stale", "status": "BLOCKED", "terminal_status": "BLOCKED", "reason_code": "SOURCE_STALE"},
                {"scenario_id": "incompatible", "status": "FAILED", "terminal_status": "FAILED", "reason_code": "UNSUPPORTED_CONTRACT"},
                {"scenario_id": "dirty-source", "status": "BLOCKED", "terminal_status": "BLOCKED", "reason_code": "SOURCE_DIRTY"},
                {"scenario_id": "replay", "status": "PASSED", "terminal_status": "REPLAYED", "reason_code": "REPLAY_IDEMPOTENT"},
            ],
            "acceptance": {
                "clean_exchange": True,
                "external_validation_unperformed": True,
                "research_result_dry_run": True,
                "tamper_terminal": True,
                "stale_terminal": True,
                "incompatible_terminal": True,
                "dirty_source_terminal": True,
                "replay_idempotent": True,
                "no_child_mutation": True,
                "no_remote_mutation": True,
            },
            "remote_operations": [],
            "child_mutations": [],
        }

    def test_valid_terminal_matrix_is_accepted(self) -> None:
        self.assertEqual([], validate_exchange_e2e(self.report))

    def test_missing_scenario_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.report)
        invalid["scenarios"] = invalid["scenarios"][:-1]
        errors = "\n".join(validate_exchange_e2e(invalid))
        self.assertIn("expected terminal cases", errors)

    def test_unperformed_external_validation_is_required(self) -> None:
        invalid = copy.deepcopy(self.report)
        invalid["normal_exchange"]["result_statuses"] = []
        invalid["normal_exchange"]["external_validation_required"] = False
        errors = "\n".join(validate_exchange_e2e(invalid))
        self.assertIn("unperformed work", errors)
        self.assertIn("external_validation_required", errors)

    def test_remote_and_child_mutations_are_rejected(self) -> None:
        invalid = copy.deepcopy(self.report)
        invalid["remote_operations"] = ["CREATE"]
        invalid["child_mutations"] = ["WRITE"]
        errors = "\n".join(validate_exchange_e2e(invalid))
        self.assertIn("remote or child mutation", errors)

    def test_e2e_schema_is_versioned_and_networkless(self) -> None:
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "schemas/production-exchange-e2e.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("production-exchange-e2e/v1", schema["properties"]["contract_version"]["const"])
        self.assertEqual("disabled", schema["properties"]["network"]["const"])
        self.assertEqual([], schema["properties"]["remote_operations"]["const"])


if __name__ == "__main__":
    unittest.main()
