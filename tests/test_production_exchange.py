from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.production_exchange import validate_exchange_evidence


class ProductionExchangeEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = {
            "contract_version": "production-exchange-evidence/v1",
            "run_id": "PRODUCTION-EXCHANGE-001:test",
            "mode": "immutable-networkless",
            "status": "PASSED",
            "stages": [
                {
                    "stage_id": "research-handoff",
                    "owner_repository": "agentic-art-research",
                    "source_commit": "a" * 40,
                    "command": "python3 tools/export_handoff.py RESEARCH_PROJECT --root RESEARCH_ROOT --output HANDOFF_OUTPUT",
                    "contract_version": "production-handoff/v1",
                    "semantic_hash": "sha256:" + "1" * 64,
                    "status": "PASSED",
                    "terminal_status": "HANDOFF_EXPORTED",
                    "output_locator": "run://PRODUCTION-EXCHANGE-001:test/handoff",
                },
                {
                    "stage_id": "production-result",
                    "owner_repository": "agentic-art-production",
                    "source_commit": "b" * 40,
                    "command": "python3 tools/export_result.py --project-root PRODUCTION_PROJECT --output RESULT_OUTPUT --format json",
                    "contract_version": "production-result/v1",
                    "semantic_hash": "sha256:" + "2" * 64,
                    "status": "PASSED",
                    "terminal_status": "RESULT_EXPORTED",
                    "output_locator": "run://PRODUCTION-EXCHANGE-001:test/result",
                },
            ],
            "remote_operations": [],
            "child_mutations": [],
            "acceptance": {
                "research_handoff_exported": True,
                "production_handoff_accepted": True,
                "production_result_exported": True,
                "research_result_dry_run": True,
                "child_schema_not_copied": True,
                "adjacent_worktree_not_read": True,
                "external_effects_not_run": True,
            },
            "privacy": {
                "raw_bundle_stored": False,
                "raw_asset_body_stored": False,
                "sensitive_data_stored": False,
                "opaque_paths_only": True,
            },
        }

    def test_valid_evidence_preserves_reference_only_boundary(self) -> None:
        self.assertEqual([], validate_exchange_evidence(self.evidence))

    def test_remote_mutation_and_raw_data_are_rejected(self) -> None:
        invalid = copy.deepcopy(self.evidence)
        invalid["remote_operations"] = ["CREATE"]
        invalid["stages"][0]["command"] = "python3 export; upload"
        invalid["privacy"]["raw_bundle_stored"] = True
        errors = validate_exchange_evidence(invalid)
        rendered = "\n".join(errors)
        self.assertIn("remote or child mutation", rendered)
        self.assertIn("shell control syntax", rendered)
        self.assertIn("must be false", rendered)

    def test_run_locator_and_provenance_are_required(self) -> None:
        invalid = copy.deepcopy(self.evidence)
        invalid["stages"][0]["source_commit"] = "not-a-commit"
        invalid["stages"][0]["output_locator"] = "path/to/output"
        errors = validate_exchange_evidence(invalid)
        rendered = "\n".join(errors)
        self.assertIn("40-character SHA", rendered)
        self.assertIn("scoped to run_id", rendered)

    def test_check_cli_accepts_and_rejects_evidence(self) -> None:
        from tools.production_exchange import main

        with tempfile.TemporaryDirectory(prefix="production-exchange-test-") as temporary:
            path = Path(temporary) / "evidence.json"
            path.write_text(json.dumps(self.evidence) + "\n", encoding="utf-8")
            self.assertEqual(
                0,
                main([
                    "--check",
                    "--evidence",
                    str(path),
                    "--workspace-root",
                    temporary,
                    "--output-root",
                    temporary,
                    "--run-id",
                    self.evidence["run_id"],
                    "--generated-at",
                    "2026-08-13T07:35:00+09:00",
                ]),
            )
            broken = copy.deepcopy(self.evidence)
            broken["stages"][0]["output_locator"] = "unsafe"
            path.write_text(json.dumps(broken) + "\n", encoding="utf-8")
            self.assertEqual(
                2,
                main([
                    "--check",
                    "--evidence",
                    str(path),
                    "--workspace-root",
                    temporary,
                    "--output-root",
                    temporary,
                    "--run-id",
                    self.evidence["run_id"],
                    "--generated-at",
                    "2026-08-13T07:35:00+09:00",
                ]),
            )


if __name__ == "__main__":
    unittest.main()
