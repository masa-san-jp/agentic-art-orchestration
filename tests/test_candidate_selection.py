from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("candidate_selection", ROOT / "tools/candidate_selection.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CandidateSelectionTests(unittest.TestCase):
    def load_inputs(self) -> tuple[dict, dict, list[dict], dict]:
        signals = MODULE.load_fixture(ROOT / "tests/fixtures/v12-candidates")
        registry = MODULE.load_yaml(ROOT / "config/transformation-rules.yaml")
        candidate_space = MODULE.build_candidate_space(signals, registry)
        gate_report = MODULE.build_gate_report(candidate_space, signals, registry)
        return candidate_space, gate_report, signals, registry

    def test_selection_schema_is_versioned_and_provenance_preserving(self):
        schema = MODULE.load_json(ROOT / "schemas/research-selection.schema.json")
        self.assertEqual("research-selection/v1", schema["properties"]["contract_version"]["const"])
        self.assertIn("source_commit", schema["$defs"]["input_ref"]["required"])
        self.assertIn("seed", schema["required"])

    def test_same_project_snapshot_rules_and_seed_are_identical(self):
        candidate_space, gate_report, signals, registry = self.load_inputs()
        first = MODULE.build_selection(candidate_space, gate_report, "project-alpha", "seed-a")
        second = MODULE.build_selection(copy.deepcopy(candidate_space), copy.deepcopy(gate_report), "project-alpha", "seed-a")
        self.assertEqual(first, second)
        self.assertEqual(MODULE.canonical_json(first), MODULE.canonical_json(second))
        selected = first["selected_candidates"][0]
        self.assertEqual(candidate_space["candidates"][0]["candidate_id"], selected["candidate_id"])
        self.assertEqual(
            {ref["source_commit"] for refs in candidate_space["candidates"][0]["inputs"].values() for ref in refs},
            {ref["source_commit"] for refs in selected["inputs"].values() for ref in refs},
        )

    def test_different_seed_changes_only_selection_metadata_or_candidate_order(self):
        candidate_space, gate_report, _signals, _registry = self.load_inputs()
        first = MODULE.build_selection(candidate_space, gate_report, "project-alpha", "seed-a")
        second = MODULE.build_selection(candidate_space, gate_report, "project-alpha", "seed-b")
        self.assertNotEqual(first["seed"], second["seed"])
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertEqual(first["rule_set_hash"], second["rule_set_hash"])
        self.assertEqual(first["selected_candidates"][0]["candidate_id"], second["selected_candidates"][0]["candidate_id"])
        self.assertNotEqual(first["selected_candidates"][0]["selection_score"], second["selected_candidates"][0]["selection_score"])

    def test_multiple_candidates_are_selected_by_seeded_rank(self):
        candidate_space, _gate_report, signals, registry = self.load_inputs()
        extra = copy.deepcopy(signals[0])
        extra["signal_id"] = "self:derived-002"
        extra["source"]["entity_ids"] = ["self-entity-002"]
        extra["source"]["locators"] = ["derived/self-entity-002"]
        extra["evidence_refs"][0]["entity_id"] = "self-entity-002"
        signals.append(extra)
        candidate_space = MODULE.build_candidate_space(signals, registry)
        gate_report = MODULE.build_gate_report(candidate_space, signals, registry)
        selected = MODULE.build_selection(candidate_space, gate_report, "project-alpha", "seed-a", 2)
        self.assertEqual(2, selected["selected_count"])
        self.assertEqual([1, 2], [item["rank"] for item in selected["selected_candidates"]])
        self.assertEqual(2, len({item["candidate_id"] for item in selected["selected_candidates"]}))

    def test_rejected_candidates_cannot_be_selected(self):
        candidate_space, gate_report, _signals, _registry = self.load_inputs()
        gate_report["evaluations"][0]["overall_status"] = "REJECT"
        for gate in gate_report["evaluations"][0]["gates"]:
            gate["status"] = "REJECT"
            gate["reason_code"] = {
                "personal-specificity": "missing-personal-signal",
                "historical-specificity": "missing-historical-signal",
                "contemporary-specificity": "missing-contemporary-signal",
                "provenance": "missing-provenance",
                "genericness": "generic-candidate",
                "counterfactual": "counterfactual-failure",
            }[gate["gate_id"]]
        with self.assertRaisesRegex(ValueError, "no candidate passed all gates"):
            MODULE.build_selection(candidate_space, gate_report, "project-alpha", "seed-a")

    def test_selection_validator_rejects_lost_provenance(self):
        candidate_space, gate_report, _signals, _registry = self.load_inputs()
        selection = MODULE.build_selection(candidate_space, gate_report, "project-alpha", "seed-a")
        del selection["selected_candidates"][0]["inputs"]["self"][0]["source_commit"]
        errors = MODULE.validate_selection(selection, "fixture:selection-provenance")
        self.assertTrue(any("source_commit" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
