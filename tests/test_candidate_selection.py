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

    def test_intent_normalization_uses_nfkc_casefold_and_single_spaces(self):
        self.assertEqual("日本", MODULE.normalize_intent(" 日本 "))
        self.assertEqual(["^日", "日本", "本$"], sorted(MODULE._bigram_multiset("日本")))
        self.assertEqual(["^a", "a$"], sorted(MODULE._bigram_multiset(MODULE.normalize_intent("Ａ"))))
        self.assertEqual("é", MODULE.normalize_intent("e\u0301"))
        self.assertEqual("abc", MODULE.normalize_intent("ＡＢＣ"))
        self.assertEqual("one two three", MODULE.normalize_intent("  ONE\t\n two   THREE  "))
        with self.assertRaisesRegex(ValueError, "non-whitespace"):
            MODULE.normalize_intent(" \t\n")

    def test_same_project_snapshot_rules_and_seed_are_identical(self):
        candidate_space, gate_report, signals, registry = self.load_inputs()
        first = MODULE.build_selection(candidate_space, gate_report, "project-alpha", "seed-a")
        second = MODULE.build_selection(copy.deepcopy(candidate_space), copy.deepcopy(gate_report), "project-alpha", "seed-a")
        self.assertEqual(first, second)
        self.assertEqual(MODULE.canonical_json(first), MODULE.canonical_json(second))
        selected = first["selected_candidates"][0]
        self.assertIn(selected["candidate_id"], {item["candidate_id"] for item in candidate_space["candidates"]})
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
        self.assertIn(first["selected_candidates"][0]["candidate_id"], {item["candidate_id"] for item in candidate_space["candidates"]})
        self.assertIn(second["selected_candidates"][0]["candidate_id"], {item["candidate_id"] for item in candidate_space["candidates"]})
        self.assertNotEqual(first["selected_candidates"][0]["selection_score"], second["selected_candidates"][0]["selection_score"])

    def test_intent_selection_is_deterministic_and_changes_the_top_candidate(self):
        candidate_space, gate_report, signals = self.diverse_inputs()
        first = MODULE.build_selection(
            candidate_space,
            gate_report,
            "project-alpha",
            "seed-a",
            intent="specificity versus privacy",
            signals=signals,
        )
        second = MODULE.build_selection(
            copy.deepcopy(candidate_space),
            copy.deepcopy(gate_report),
            "project-alpha",
            "seed-a",
            intent="specificity versus privacy",
            signals=copy.deepcopy(signals),
        )
        self.assertEqual(first, second)
        self.assertEqual("research-selection/v2", first["contract_version"])
        self.assertEqual("intent-rank/v1", first["intent_algorithm"])
        self.assertNotIn("specificity versus privacy", MODULE.canonical_json(first))
        second_intent = MODULE.build_selection(
            candidate_space,
            gate_report,
            "project-alpha",
            "seed-a",
            intent="review before reuse",
            signals=signals,
        )
        self.assertNotEqual(
            first["selected_candidates"][0]["candidate_id"],
            second_intent["selected_candidates"][0]["candidate_id"],
        )
        self.assertEqual("tensions", first["selected_candidates"][0]["composition"]["personal_tension"]["attribute"])
        self.assertEqual("recurring_patterns", second_intent["selected_candidates"][0]["composition"]["personal_tension"]["attribute"])

    def test_intent_ranking_never_selects_a_gate_failed_top_candidate(self):
        candidate_space, gate_report, signals = self.diverse_inputs()
        candidates = {candidate["candidate_id"]: candidate for candidate in candidate_space["candidates"]}
        target_id = max(
            candidates,
            key=lambda candidate_id: MODULE.build_intent_scores(
                candidates[candidate_id], signals, "specificity versus privacy"
            )["intent_score"],
        )
        rejected_gates = copy.deepcopy(gate_report)
        evaluation = next(item for item in rejected_gates["evaluations"] if item["candidate_id"] == target_id)
        evaluation["overall_status"] = "REJECT"
        evaluation["gates"][0]["status"] = "REJECT"
        evaluation["gates"][0]["reason_code"] = "missing-personal-signal"
        selected = MODULE.build_selection(
            candidate_space,
            rejected_gates,
            "project-alpha",
            "seed-a",
            intent="specificity versus privacy",
            signals=signals,
        )
        self.assertNotEqual(target_id, selected["selected_candidates"][0]["candidate_id"])

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
        for evaluation in gate_report["evaluations"]:
            evaluation["overall_status"] = "REJECT"
            for gate in evaluation["gates"]:
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

    def diverse_inputs(self) -> tuple[dict, dict, list[dict]]:
        signals = MODULE.load_fixture(ROOT / "tests/fixtures/v12-candidates")
        self_signal = signals[0]
        self_signal["domain"]["self_model"]["tensions"] = ["specificity versus privacy", "tension-2"]
        self_signal["domain"]["self_model"]["recurring_patterns"] = ["review before reuse", "pattern-2"]
        art_history = signals[1]
        for index in range(2, 26):
            extra = copy.deepcopy(art_history)
            extra["signal_id"] = f"art-history:entity-{index:03d}"
            extra["source"]["entity_ids"] = [f"art-entity-{index:03d}"]
            extra["source"]["locators"] = [f"entities/art-entity-{index:03d}"]
            extra["evidence_refs"][0]["entity_id"] = f"art-entity-{index:03d}"
            extra["evidence_refs"][0]["locator"] = f"art-history/evidence/source-{index:03d}"
            signals.append(extra)
        registry = MODULE.load_yaml(ROOT / "config/transformation-rules.yaml")
        candidate_space = MODULE.build_candidate_space(signals, registry)
        gate_report = MODULE.build_gate_report(candidate_space, signals, registry)
        return candidate_space, gate_report, signals

    def test_self_diversity_report_is_opaque_and_marks_below_three_anchors_limited(self):
        candidate_space, _gate_report, signals, _registry = self.load_inputs()
        report = MODULE.build_self_diversity_report(signals, candidate_space, selection_limit=10)
        self.assertEqual("PASS_LIMITED_DIVERSITY", report["status"])
        self.assertEqual(2, report["eligible_anchor_count"])
        self.assertEqual({"tensions": 1, "recurring_patterns": 1}, report["attribute_counts"])
        rendered = MODULE.canonical_json(report)
        self.assertNotIn("specificity versus privacy", rendered)
        self.assertNotIn("review before reuse", rendered)
        selection = MODULE.build_selection(
            candidate_space,
            _gate_report,
            "project-alpha",
            "seed-a",
            1,
            require_self_diversity=True,
            signals=signals,
        )
        selected_report = MODULE.build_self_diversity_report(signals, candidate_space, selection["selected_candidates"], 1)
        self.assertEqual("PASS_LIMITED_DIVERSITY", selected_report["status"])

    def test_self_diversity_selection_round_robins_four_anchors(self):
        candidate_space, gate_report, signals = self.diverse_inputs()
        self.assertEqual(100, candidate_space["candidate_count"])
        first = MODULE.build_selection(
            candidate_space,
            gate_report,
            "project-alpha",
            "seed-a",
            10,
            require_self_diversity=True,
            signals=signals,
        )
        second = MODULE.build_selection(
            copy.deepcopy(candidate_space),
            copy.deepcopy(gate_report),
            "project-alpha",
            "seed-a",
            10,
            require_self_diversity=True,
            signals=copy.deepcopy(signals),
        )
        self.assertEqual(first, second)
        report = MODULE.build_self_diversity_report(signals, candidate_space, first["selected_candidates"], 10)
        self.assertEqual("PASS", report["status"])
        self.assertEqual(4, report["eligible_anchor_count"])
        self.assertGreaterEqual(report["distinct_selected_count"], 3)
        self.assertLessEqual(report["max_anchor_share"], 0.4)
        self.assertEqual(10, report["selected_count"])
        self.assertTrue(
            all(
                {ref["source_commit"] for refs in candidate["inputs"].values() for ref in refs}
                for candidate in first["selected_candidates"]
            )
        )
        full = MODULE.build_selection(
            candidate_space,
            gate_report,
            "project-alpha",
            "seed-a",
            100,
            require_self_diversity=True,
            signals=signals,
        )
        full_report = MODULE.build_self_diversity_report(signals, candidate_space, full["selected_candidates"], 100)
        self.assertEqual(100, full["selected_count"])
        self.assertEqual(4, full_report["distinct_selected_count"])
        self.assertLessEqual(full_report["max_anchor_share"], 0.4)

    def test_one_anchor_is_accepted_as_limited_diversity(self):
        candidate_space, gate_report, signals, registry = self.load_inputs()
        signals[0]["domain"]["self_model"]["recurring_patterns"] = []
        reduced_space = MODULE.build_candidate_space(signals, registry)
        reduced_gates = MODULE.build_gate_report(reduced_space, signals, registry)
        report = MODULE.build_self_diversity_report(signals, reduced_space, selection_limit=1)
        self.assertEqual(1, report["eligible_anchor_count"])
        self.assertEqual("PASS_LIMITED_DIVERSITY", report["status"])
        selection = MODULE.build_selection(
            reduced_space,
            reduced_gates,
            "project-alpha",
            "seed-a",
            1,
            require_self_diversity=True,
            signals=signals,
        )
        self.assertEqual(1, selection["selected_count"])

    def test_one_recurring_pattern_anchor_is_selected_with_its_declared_attribute(self):
        candidate_space, gate_report, signals, registry = self.load_inputs()
        signals[0]["domain"]["self_model"]["tensions"] = []
        reduced_space = MODULE.build_candidate_space(signals, registry)
        reduced_gates = MODULE.build_gate_report(reduced_space, signals, registry)
        selection = MODULE.build_selection(
            reduced_space,
            reduced_gates,
            "project-recurring-anchor",
            "seed-a",
            1,
            require_self_diversity=True,
            signals=signals,
        )
        self.assertEqual("recurring_patterns", selection["selected_candidates"][0]["composition"]["personal_tension"]["attribute"])

    def test_zero_anchors_still_block_strict_selection(self):
        candidate_space, gate_report, signals, registry = self.load_inputs()
        signals[0]["domain"]["self_model"]["tensions"] = []
        signals[0]["domain"]["self_model"]["recurring_patterns"] = []
        reduced_space = MODULE.build_candidate_space(signals, registry)
        reduced_gates = MODULE.build_gate_report(reduced_space, signals, registry)
        report = MODULE.build_self_diversity_report(signals, reduced_space, selection_limit=1)
        self.assertEqual(0, report["eligible_anchor_count"])
        self.assertEqual("INSUFFICIENT_SELF_DIVERSITY", report["status"])
        with self.assertRaisesRegex(ValueError, "no candidate passed all gates"):
            MODULE.build_selection(
                reduced_space,
                reduced_gates,
                "project-alpha",
                "seed-a",
                1,
                require_self_diversity=True,
                signals=signals,
            )


if __name__ == "__main__":
    unittest.main()
