from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("candidate_gates", ROOT / "tools/candidate_gates.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CandidateGateTests(unittest.TestCase):
    def load_inputs(self) -> tuple[dict, list[dict], dict]:
        signals = MODULE.load_fixture(ROOT / "tests/fixtures/v12-candidates")
        registry = MODULE.load_yaml(ROOT / "config/transformation-rules.yaml")
        candidate_space = MODULE.build_candidate_space(signals, registry)
        return candidate_space, signals, registry

    def test_gate_schema_is_explicit_and_reference_only(self):
        schema = MODULE.load_json(ROOT / "schemas/research-candidate-gates.schema.json")
        self.assertEqual("research-candidate-gates/v1", schema["properties"]["contract_version"]["const"])
        self.assertEqual(6, schema["$defs"]["evaluation"]["properties"]["gates"]["maxItems"])
        self.assertNotIn("statement", schema["$defs"]["gate"]["properties"])

    def test_clean_candidate_passes_all_six_gates(self):
        candidate_space, signals, registry = self.load_inputs()
        report = MODULE.build_gate_report(candidate_space, signals, registry)
        self.assertEqual(1, len(report["evaluations"]))
        for evaluation in report["evaluations"]:
            self.assertEqual("PASS", evaluation["overall_status"])
            self.assertEqual(set(MODULE.GATE_IDS), {gate["gate_id"] for gate in evaluation["gates"]})
            self.assertTrue(all(gate["status"] == "PASS" for gate in evaluation["gates"]))
            self.assertTrue(all(gate["reason_code"] is None for gate in evaluation["gates"]))

    def test_same_inputs_produce_byte_identical_gate_report(self):
        candidate_space, signals, registry = self.load_inputs()
        first = MODULE.build_gate_report(candidate_space, signals, registry)
        second = MODULE.build_gate_report(copy.deepcopy(candidate_space), list(reversed(copy.deepcopy(signals))), copy.deepcopy(registry))
        self.assertEqual(first, second)
        self.assertEqual(MODULE.canonical_json(first), MODULE.canonical_json(second))

    def test_generic_candidate_is_rejected_with_explicit_evidence(self):
        candidate_space, signals, registry = self.load_inputs()
        candidate = candidate_space["candidates"][0]
        self_signal = candidate["inputs"]["self"][0]
        for slot in candidate["composition"].values():
            slot.update({"signal_id": self_signal["signal_id"], "signal_kind": "self", "attribute": "tensions"})
        report = MODULE.build_gate_report(candidate_space, signals, registry)
        evaluation = report["evaluations"][0]
        by_id = {gate["gate_id"]: gate for gate in evaluation["gates"]}
        self.assertEqual("REJECT", evaluation["overall_status"])
        self.assertEqual("REJECT", by_id["genericness"]["status"])
        self.assertEqual("generic-candidate", by_id["genericness"]["reason_code"])
        self.assertEqual("REJECT", by_id["counterfactual"]["status"])
        self.assertTrue(by_id["genericness"]["evidence"])

    def test_source_dependency_mismatch_is_rejected_by_provenance_gate(self):
        candidate_space, signals, registry = self.load_inputs()
        candidate_space["candidates"][0]["inputs"]["self"][0]["source_commit"] = "0" * 40
        report = MODULE.build_gate_report(candidate_space, signals, registry)
        evaluation = report["evaluations"][0]
        provenance = next(gate for gate in evaluation["gates"] if gate["gate_id"] == "provenance")
        self.assertEqual("REJECT", evaluation["overall_status"])
        self.assertEqual("REJECT", provenance["status"])
        self.assertEqual("missing-provenance", provenance["reason_code"])

    def test_gate_validator_rejects_status_reason_mismatch(self):
        candidate_space, signals, registry = self.load_inputs()
        report = MODULE.build_gate_report(candidate_space, signals, registry)
        gate = report["evaluations"][0]["gates"][0]
        gate["status"] = "REJECT"
        errors = MODULE.validate_candidate_gates(report, "fixture:gate-mismatch")
        rendered = "\n".join(errors)
        self.assertIn("reason_code", rendered)
        self.assertIn("remediation:", rendered)


if __name__ == "__main__":
    unittest.main()
