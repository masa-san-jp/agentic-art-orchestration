from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.adapters import AdapterError, adapt_art_history_signal
from tools.build_research_request import build_request
from tools.candidate_gates import build_gate_report, evaluate_candidate
from tools.candidate_selection import build_selection
from tools.candidate_space import build_candidate_space, build_diversity_report, load_fixture, main
from tools.proposition_provenance import build_provenance
from tools.validate import load_json, load_yaml, validate_signal

ROOT = Path(__file__).resolve().parents[1]


class MethodSeedTests(unittest.TestCase):
    def record(self):
        return load_json(ROOT / "tests/fixtures/signal/method_adapter_input.json")

    def inputs(self):
        signals = load_fixture(ROOT / "tests/fixtures/v12-candidates")
        registry = load_yaml(ROOT / "config/transformation-rules.yaml")
        return signals, registry

    def test_adapter_retains_sourced_method_and_uncertainty_without_graph_copy(self):
        record = self.record()
        original = copy.deepcopy(record)
        signal = adapt_art_history_signal(record)
        self.assertEqual(original, record)
        self.assertEqual([], validate_signal(signal))
        self.assertEqual(record["method"], signal["domain"]["art_history"]["method"])
        self.assertEqual(record["source_refs"], signal["domain"]["art_history"]["source_refs"])
        self.assertEqual("unknown", signal["validity"]["status"])
        self.assertEqual("inferred", signal["certainty"]["level"])
        self.assertIn(record["source_refs"][0], [ref["locator"] for ref in signal["evidence_refs"]])

    def test_missing_or_invalid_method_sources_are_rejected(self):
        for refs in (None, [], [""], ["idea:unsourced"], ["https://"], ["https://example.test/has space"], [{}], [[]]):
            with self.subTest(refs=refs):
                record = self.record()
                if refs is None:
                    del record["source_refs"]
                else:
                    record["source_refs"] = refs
                with self.assertRaises(AdapterError):
                    adapt_art_history_signal(record)
        signal = adapt_art_history_signal(self.record())
        signal["evidence_refs"] = signal["evidence_refs"][:1]
        self.assertTrue(validate_signal(signal))
        signals, registry = self.inputs()
        with self.assertRaisesRegex(ValueError, "source_refs"):
            build_candidate_space(signals + [signal], registry)

    def test_incomplete_method_is_rejected_even_with_a_source(self):
        for field in ("fixes", "varies", "requires", "origin_domain"):
            record = self.record()
            record["method"].pop(field)
            with self.subTest(field=field), self.assertRaises(AdapterError):
                adapt_art_history_signal(record)
        record = self.record()
        record["method"]["fixes"] = ["   "]
        with self.assertRaises(AdapterError):
            adapt_art_history_signal(record)

    def test_same_fixture_gains_a_method_lineage_and_preserves_r17(self):
        signals, registry = self.inputs()
        before = build_candidate_space(signals, registry)
        method = adapt_art_history_signal(self.record())
        after = build_candidate_space(signals + [method], registry)
        self.assertEqual(1, before["candidate_count"])
        self.assertEqual(2, after["candidate_count"])
        reports = [build_diversity_report(space, inputs) for space, inputs in
                   ((before, signals), (after, signals + [method]))]
        self.assertEqual([1, 2], [report["distinct_lineage_count"] for report in reports])
        self.assertEqual([1, 1], [report["distinct_self_marketing_lineage_count"] for report in reports])
        self.assertEqual([1, 2], [report["distinct_art_history_anchor_combinations"] for report in reports])
        legacy = next(c for c in after["candidates"] if c["rule_id"] == "R17")
        self.assertEqual(before["candidates"][0]["composition"], legacy["composition"])
        self.assertEqual(before["candidates"][0]["inputs"], legacy["inputs"])
        method_candidate = next(c for c in after["candidates"] if c["rule_id"] == "R18")
        self.assertEqual("method", method_candidate["composition"]["historical_operation"]["attribute"])
        serialized = json.dumps(reports)
        for value in signals[0]["domain"]["self_model"]["tensions"]:
            self.assertNotIn(value, serialized)

    def test_diversity_cli_compares_before_and_after_without_writing_artifacts(self):
        signals, _registry = self.inputs()
        counts = []
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            for extra in ([], [adapt_art_history_signal(self.record())]):
                inputs = signals + extra
                paths = []
                for index, signal in enumerate(inputs):
                    name = f"signal-{index}.json"
                    (fixture / name).write_text(json.dumps(signal), encoding="utf-8")
                    paths.append(name)
                (fixture / "portfolio.json").write_text(json.dumps({"signal_files": paths}), encoding="utf-8")
                stdout = io.StringIO()
                with patch.object(sys, "argv", ["candidate_space.py", "--fixture", str(fixture), "--report", "diversity"]), contextlib.redirect_stdout(stdout):
                    self.assertEqual(0, main())
                counts.append(json.loads(stdout.getvalue())["distinct_lineage_count"])
        self.assertEqual([1, 2], counts)

    def test_method_with_relations_is_one_method_seed_not_duplicate_studies(self):
        signals, registry = self.inputs()
        record = self.record()
        record["relations"] = load_json(ROOT / "tests/fixtures/signal/art_adapter_input.json")["relations"]
        record["validity"]["status"] = "valid"
        method = adapt_art_history_signal(record)
        space = build_candidate_space([signals[0], method, signals[2]], registry)
        self.assertEqual(["R18"], [c["rule_id"] for c in space["candidates"]])
        self.assertEqual(record["relations"], method["domain"]["art_history"]["relations"])
        self.assertEqual("PASS", build_gate_report(space, [signals[0], method, signals[2]], registry)["evaluations"][0]["overall_status"])

    def test_method_seed_passes_gates_and_reaches_the_research_question(self):
        signals, registry = self.inputs()
        method = adapt_art_history_signal(self.record())
        signals = [signals[0], method, signals[2]]
        space = build_candidate_space(signals, registry)
        self.assertEqual(["R18"], [c["rule_id"] for c in space["candidates"]])
        gates = build_gate_report(space, signals, registry)
        self.assertEqual("PASS", gates["evaluations"][0]["overall_status"])
        selection = build_selection(space, gates, "method-fixture", "fixture-seed")
        provenance = build_provenance(selection, space, gates, signals, registry)
        request = build_request(provenance["propositions"][0], {s["signal_id"]: s for s in signals},
                                request_id="RR001", slug="method-fixture", title="Method fixture",
                                requested_at=method["generated_at"], commit="a" * 40,
                                deadline=None, creator_id=None, full_names={"art-history": "masa-san-jp/art-history-notes"})
        question = request["intent"]["creative_question"]
        for field in ("fixes", "varies", "requires"):
            self.assertIn(method["domain"]["art_history"]["method"][field][0], question)
        self.assertIn("computation", question)
        self.assertIn("https://example.test/method", json.dumps(request))
        self.assertNotIn("blob/" + method["source"]["commit"] + "/https:", json.dumps(request))

    def test_gate_rejects_missing_sources_and_stale_method_without_promoting_validity(self):
        signals, registry = self.inputs()
        method = adapt_art_history_signal(self.record())
        signals.append(method)
        space = build_candidate_space(signals, registry)
        candidate = next(c for c in space["candidates"] if c["rule_id"] == "R18")
        rule = next(r for r in registry["rules"] if r["rule_id"] == "R18")
        for mutation in ("no-source", "stale", "wrong-rule"):
            bad = copy.deepcopy(method)
            selected_rule = copy.deepcopy(rule)
            if mutation == "no-source":
                bad["domain"]["art_history"]["source_refs"] = []
            elif mutation == "stale":
                bad["freshness"]["status"] = "stale"
            else:
                selected_rule["composition"]["slots"]["historical_operation"]["attribute"] = "relations"
            evaluation = evaluate_candidate(candidate, {s["signal_id"]: s for s in signals[:-1]} | {bad["signal_id"]: bad}, selected_rule)
            gate = next(g for g in evaluation["gates"] if g["gate_id"] == "historical-specificity")
            self.assertEqual("REJECT", gate["status"])
        self.assertEqual("unknown", method["validity"]["status"])


if __name__ == "__main__":
    unittest.main()
