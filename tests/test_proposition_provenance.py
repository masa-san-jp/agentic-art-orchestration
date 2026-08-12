from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

from tools.candidate_gates import build_gate_report
from tools.candidate_selection import build_selection
from tools.candidate_space import build_candidate_space


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("proposition_provenance", ROOT / "tools/proposition_provenance.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class PropositionProvenanceTests(unittest.TestCase):
    def load_inputs(self) -> tuple[dict, dict, dict, list[dict], dict]:
        signals = MODULE.load_fixture(ROOT / "tests/fixtures/v12-candidates")
        registry = MODULE.load_yaml(ROOT / "config/transformation-rules.yaml")
        candidate_space = build_candidate_space(signals, registry)
        gate_report = build_gate_report(candidate_space, signals, registry)
        selection = build_selection(candidate_space, gate_report, "project-alpha", "seed-a")
        return selection, candidate_space, gate_report, signals, registry

    def test_schema_is_versioned_and_reference_only(self):
        schema = MODULE.load_json(ROOT / "schemas/research-provenance.schema.json")
        self.assertEqual("research-provenance/v1", schema["properties"]["contract_version"]["const"])
        self.assertIn("selection_decision", schema["required"])
        self.assertIn("evidence_locator", schema["$defs"]["provenance_ref"]["required"])
        self.assertNotIn("statement", schema["$defs"]["proposition"]["properties"])

    def test_trace_is_deterministic_and_carries_selection_rule_and_source_provenance(self):
        selection, candidate_space, gate_report, signals, registry = self.load_inputs()
        first = MODULE.build_provenance(selection, candidate_space, gate_report, signals, registry)
        second = MODULE.build_provenance(
            copy.deepcopy(selection),
            copy.deepcopy(candidate_space),
            copy.deepcopy(gate_report),
            copy.deepcopy(signals),
            copy.deepcopy(registry),
        )
        self.assertEqual(first, second)
        self.assertEqual(MODULE.canonical_json(first), MODULE.canonical_json(second))
        proposition = first["propositions"][0]
        self.assertEqual("R17", proposition["rule_id"])
        self.assertEqual(selection["selected_candidates"][0]["candidate_id"], proposition["candidate_id"])
        self.assertEqual({"self", "art-history", "marketing"}, {item["signal_kind"] for item in proposition["normalized_signals"]})
        for slot in proposition["structured_output"]["slots"].values():
            self.assertTrue(slot["source_repository"])
            self.assertEqual(40, len(slot["source_commit"]))
            self.assertTrue(slot["evidence_locator"])
        self.assertNotIn("statement", MODULE.canonical_json(first))

    def test_selection_candidate_mutation_is_rejected(self):
        selection, candidate_space, gate_report, signals, registry = self.load_inputs()
        selection["selected_candidates"][0]["inputs"]["self"][0]["source_commit"] = "f" * 40
        with self.assertRaisesRegex(ValueError, "differs from candidate space"):
            MODULE.build_provenance(selection, candidate_space, gate_report, signals, registry)

    def test_normalized_signal_source_mismatch_is_rejected(self):
        selection, candidate_space, gate_report, signals, registry = self.load_inputs()
        signals[0]["source"]["commit"] = "f" * 40
        with self.assertRaisesRegex(ValueError, "loses source provenance"):
            MODULE.build_provenance(selection, candidate_space, gate_report, signals, registry)

    def test_output_validator_rejects_untraceable_evidence_locator(self):
        selection, candidate_space, gate_report, signals, registry = self.load_inputs()
        result = MODULE.build_provenance(selection, candidate_space, gate_report, signals, registry)
        invalid = copy.deepcopy(result)
        invalid["propositions"][0]["structured_output"]["slots"]["personal_tension"]["evidence_locator"] = "unrelated/evidence"
        errors = MODULE.validate_research_provenance(invalid, "fixture:provenance")
        rendered = "\n".join(errors)
        self.assertIn("untraceable evidence locator", rendered)
        self.assertIn("remediation:", rendered)


if __name__ == "__main__":
    unittest.main()
