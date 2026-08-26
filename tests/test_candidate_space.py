from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("candidate_space", ROOT / "tools/candidate_space.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CandidateSpaceTests(unittest.TestCase):
    def load_inputs(self) -> tuple[list[dict], dict]:
        signals = MODULE.load_fixture(ROOT / "tests/fixtures/v12-candidates")
        registry = MODULE.load_yaml(ROOT / "config/transformation-rules.yaml")
        return signals, registry

    def test_candidate_schema_is_versioned_and_reference_only(self):
        schema = MODULE.load_json(ROOT / "schemas/research-candidate.schema.json")
        self.assertEqual("research-candidate/v1", schema["properties"]["contract_version"]["const"])
        self.assertIn("source_commit", schema["$defs"]["input_ref"]["required"])
        self.assertNotIn("statement", schema["$defs"]["candidate"]["properties"])

    def test_generation_preserves_ids_commits_and_locators(self):
        signals, registry = self.load_inputs()
        result = MODULE.build_candidate_space(signals, registry)
        self.assertEqual(1, result["candidate_count"])
        candidate = result["candidates"][0]
        self.assertEqual({"R17"}, {candidate["rule_id"]})
        refs = [ref for refs in candidate["inputs"].values() for ref in refs]
        self.assertEqual(
            {signal["signal_id"] for signal in signals},
            {ref["signal_id"] for ref in refs},
        )
        for signal in signals:
            ref = next(item for item in refs if item["signal_id"] == signal["signal_id"])
            self.assertEqual(signal["source"]["repository"], ref["source_repository"])
            self.assertEqual(signal["source"]["commit"], ref["source_commit"])
            self.assertEqual(signal["source"]["locators"], ref["source_locators"])
            self.assertEqual(
                [item["locator"] for item in signal["evidence_refs"]],
                ref["evidence_locators"],
            )
        self.assertEqual(
            {"self:derived-001", "art-history:entity-001", "marketing:trend-001"},
            {slot["signal_id"] for slot in candidate["composition"].values()},
        )

    def test_same_snapshot_and_rules_are_byte_identical(self):
        signals, registry = self.load_inputs()
        first = MODULE.build_candidate_space(signals, registry)
        second = MODULE.build_candidate_space(list(reversed(copy.deepcopy(signals)),), copy.deepcopy(registry))
        self.assertEqual(first, second)
        self.assertEqual(MODULE.canonical_json(first), MODULE.canonical_json(second))

    def test_multiple_signals_are_enumerated_in_stable_order(self):
        signals, registry = self.load_inputs()
        extra = copy.deepcopy(signals[0])
        extra["signal_id"] = "self:derived-002"
        extra["source"]["entity_ids"] = ["self-entity-002"]
        extra["source"]["locators"] = ["derived/self-entity-002"]
        extra["evidence_refs"][0]["entity_id"] = "self-entity-002"
        signals.append(extra)
        result = MODULE.build_candidate_space(signals, registry)
        self.assertEqual(4, result["candidate_count"])
        self.assertEqual(sorted(item["candidate_id"] for item in result["candidates"]), [item["candidate_id"] for item in result["candidates"]])

    def test_duplicate_signal_id_and_missing_kind_fail_closed(self):
        signals, registry = self.load_inputs()
        with self.assertRaisesRegex(ValueError, "duplicate signal_id"):
            MODULE.build_candidate_space(signals + [copy.deepcopy(signals[0])], registry)
        with self.assertRaisesRegex(ValueError, "missing-required-signal"):
            MODULE.build_candidate_space(signals[:2], registry)

    def test_candidate_semantics_reject_lost_provenance_or_count(self):
        signals, registry = self.load_inputs()
        result = MODULE.build_candidate_space(signals, registry)
        result["candidate_count"] = 3
        errors = MODULE.validate_candidate_space(result, "fixture:count")
        self.assertTrue(any("candidate_count" in error for error in errors))
        result = MODULE.build_candidate_space(signals, registry)
        del result["candidates"][0]["inputs"]["self"][0]["source_commit"]
        errors = MODULE.validate_candidate_space(result, "fixture:provenance")
        self.assertTrue(any("source_commit" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
