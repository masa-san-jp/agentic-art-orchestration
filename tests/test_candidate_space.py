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
        self.assertEqual({"intersection"}, {item["composition_mode"] for item in result["candidates"]})
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
        self.assertEqual("recurring_patterns", candidate["composition"]["personal_pattern"]["attribute"])
        self.assertEqual("stage", candidate["composition"]["contemporary_condition"]["attribute"])
        self.assertNotIn("contemporary_counterevidence", candidate["composition"])

    def test_art_history_and_marketing_changes_remain_distinct_intersection_mechanisms(self):
        signals, registry = self.load_inputs()
        art_history = copy.deepcopy(signals[1])
        art_history["signal_id"] = "art-history:entity-002"
        art_history["source"]["entity_ids"] = ["art-entity-002"]
        art_history["source"]["locators"] = ["relations/art-entity-002"]
        art_history["evidence_refs"][0]["entity_id"] = "art-entity-002"
        marketing = copy.deepcopy(signals[2])
        marketing["signal_id"] = "marketing:trend-002"
        marketing["source"]["entity_ids"] = ["trend-002"]
        marketing["source"]["locators"] = ["trends/trend-002"]
        marketing["evidence_refs"][0]["entity_id"] = "trend-002"
        marketing["domain"]["marketing"]["stage"] = "emerging"
        result = MODULE.build_candidate_space(signals + [art_history, marketing], registry)
        intersections = {
            (
                item["composition_mode"],
                tuple(sorted((name, slot["signal_id"], slot["attribute"]) for name, slot in item["composition"].items())),
            )
            for item in result["candidates"]
        }
        self.assertEqual(result["candidate_count"], len(intersections))
        self.assertTrue(all(mode == "intersection" for mode, _signals in intersections))

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
        self.assertEqual(2, result["candidate_count"])
        self.assertEqual(sorted(item["candidate_id"] for item in result["candidates"]), [item["candidate_id"] for item in result["candidates"]])

    def test_empty_recurring_patterns_keep_the_optional_slot(self):
        signals, registry = self.load_inputs()
        signals[0]["domain"]["self_model"]["recurring_patterns"] = []
        result = MODULE.build_candidate_space(signals, registry)
        self.assertEqual(1, result["candidate_count"])
        self.assertEqual("recurring_patterns", result["candidates"][0]["composition"]["personal_pattern"]["attribute"])

    def test_diversity_report_compares_old_and_multi_attribute_rules(self):
        """Compare a single-attribute R17 baseline against the multi-attribute rule.

        Comparison condition (deliberately *not* a replay of origin/main):
        origin/main's R17 had one ``personal_tension`` slot whose attribute
        could dynamically be either ``tensions`` or ``recurring_patterns``,
        so both attributes' values were enumerated as alternative anchors on
        that single slot. With 3 tensions and 2 recurring_patterns, main
        would report 5 distinct self anchors (3 + 2, one slot, one value
        each), not 3. The ``before`` baseline here instead keeps a single
        slot bound only to ``tensions`` (``recurring_patterns`` is dropped
        from composition entirely, not folded into the same slot), to show
        plainly what adding a second, separately-bound attribute changes.
        To keep the "after is larger" claim honest against actual
        origin/main behavior too, not just against this simplified
        baseline, the test also checks 6 (after) > 5 (the real main count).
        """
        signals, registry = self.load_inputs()
        signals[0]["domain"]["self_model"]["tensions"] = ["tension-1", "tension-2", "tension-3"]
        signals[0]["domain"]["self_model"]["recurring_patterns"] = ["pattern-1", "pattern-2"]
        baseline = copy.deepcopy(registry)
        baseline["rules"][0]["composition"]["slots"].pop("personal_pattern")
        baseline["rules"][0]["composition"]["template"] = "{personal_tension} ∩ {historical_operation} ∩ {contemporary_condition}"
        before = MODULE.build_candidate_space(signals, baseline)
        after = MODULE.build_candidate_space(signals, registry)
        before_report = MODULE.build_diversity_report(before, signals)
        after_report = MODULE.build_diversity_report(after, signals)
        self.assertEqual(3, before_report["distinct_self_anchor_combinations"])
        self.assertEqual(6, after_report["distinct_self_anchor_combinations"])
        self.assertGreater(after_report["distinct_lineage_count"], before_report["distinct_lineage_count"])
        # Honesty check against actual origin/main semantics (5 anchors from
        # one dynamically-bound slot), not just against the simplified
        # single-attribute baseline built above.
        ACTUAL_ORIGIN_MAIN_SELF_ANCHOR_COUNT = 3 + 2
        self.assertGreater(after_report["distinct_self_anchor_combinations"], ACTUAL_ORIGIN_MAIN_SELF_ANCHOR_COUNT)

    def test_resolve_personal_anchor_ids_replays_pre_254_legacy_candidates(self):
        """A candidate space built before #254 used one ``personal_tension``
        slot and a singular ``personal_anchor_id`` string identity (instead
        of today's ``personal_anchor_ids`` dict keyed by slot name). Replaying
        such a candidate must still resolve its anchor rather than silently
        returning nothing, or callers like build_self_diversity_report raise
        ValueError on data generated before this change.
        """
        signals, registry = self.load_inputs()
        candidate_space = MODULE.build_candidate_space(signals, registry)
        candidate = copy.deepcopy(candidate_space["candidates"][0])
        # Reshape to the pre-#254 single-slot form: drop personal_pattern.
        del candidate["composition"]["personal_pattern"]

        self_signal_id = candidate["composition"]["personal_tension"]["signal_id"]
        anchor = MODULE.personal_anchor_id(self_signal_id, "tensions", "specificity versus privacy")
        legacy_identity = {
            "rule_id": candidate["rule_id"],
            "snapshot_id": candidate_space["snapshot_id"],
            "signal_ids": {kind: refs[0]["signal_id"] for kind, refs in candidate["inputs"].items()},
            "personal_anchor_id": anchor,
        }
        candidate["candidate_id"] = f"candidate:{MODULE.sha256_hex(legacy_identity)[:16]}"

        resolved = MODULE.resolve_personal_anchor_ids(candidate, candidate_space, signals)
        self.assertEqual({"personal_tension": anchor}, resolved)

    def test_resolve_personal_anchor_ids_replays_legacy_candidates_with_no_anchor_field(self):
        """An even older candidate space never recorded a personal anchor at
        all; its identity hash has no personal_anchor_id/ids field. When
        exactly one eligible anchor matches the slot's signal and attribute
        unambiguously, that anchor must still be recoverable.
        """
        signals, registry = self.load_inputs()
        candidate_space = MODULE.build_candidate_space(signals, registry)
        candidate = copy.deepcopy(candidate_space["candidates"][0])
        del candidate["composition"]["personal_pattern"]

        self_signal_id = candidate["composition"]["personal_tension"]["signal_id"]
        base_identity = {
            "rule_id": candidate["rule_id"],
            "snapshot_id": candidate_space["snapshot_id"],
            "signal_ids": {kind: refs[0]["signal_id"] for kind, refs in candidate["inputs"].items()},
        }
        candidate["candidate_id"] = f"candidate:{MODULE.sha256_hex(base_identity)[:16]}"

        anchor = MODULE.personal_anchor_id(self_signal_id, "tensions", "specificity versus privacy")
        resolved = MODULE.resolve_personal_anchor_ids(candidate, candidate_space, signals)
        self.assertEqual({"personal_tension": anchor}, resolved)

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
