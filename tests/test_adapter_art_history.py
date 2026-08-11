from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.adapters import AdapterError, adapt_art_history_signal
from tools.validate import validate_signal


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/signal/art_adapter_input.json"


def load_input() -> dict:
    with FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


class ArtHistoryAdapterTests(unittest.TestCase):
    def test_entity_relation_and_provenance_export_without_graph_copy(self):
        record = load_input()
        before = copy.deepcopy(record)
        signal = adapt_art_history_signal(record)

        self.assertEqual(before, record)
        self.assertEqual([], validate_signal(signal, "fixture:art-adapter"))
        self.assertEqual("art-history", signal["source"]["repository"])
        self.assertEqual(record["commit"], signal["source"]["commit"])
        relation = signal["domain"]["art_history"]["relations"][0]
        self.assertEqual("artist-entity-001", relation["target_entity_id"])
        self.assertEqual(record["relations"][0]["certainty"], relation["certainty"])
        self.assertEqual(record["relations"][0]["evidence_refs"], relation["evidence_refs"])
        self.assertEqual(record["canonical_graph_locator"], signal["domain"]["art_history"]["canonical_graph_locator"])
        self.assertNotIn("nodes", signal["domain"]["art_history"])
        self.assertNotIn("edges", signal["domain"]["art_history"])

    def test_canonical_graph_payload_is_rejected(self):
        record = load_input()
        record["nodes"] = [{"id": "art-entity-001", "label": "synthetic"}]
        with self.assertRaisesRegex(AdapterError, "canonical graph payload.*remediation"):
            adapt_art_history_signal(record)

    def test_relation_without_stable_target_or_evidence_is_rejected(self):
        for removed in ("target_entity_id", "evidence_refs"):
            with self.subTest(removed=removed):
                record = load_input()
                del record["relations"][0][removed]
                with self.assertRaisesRegex(AdapterError, r"relations\[0\].*remediation"):
                    adapt_art_history_signal(record)

    def test_relation_cannot_copy_source_entity_as_target(self):
        record = load_input()
        record["relations"][0]["target_entity_id"] = record["entity_id"]
        with self.assertRaisesRegex(AdapterError, "repeats the source entity.*remediation"):
            adapt_art_history_signal(record)

    def test_interpretive_certainty_and_unknowns_are_forwarded(self):
        record = load_input()
        record["relations"][0]["certainty"] = {"level": "unknown"}
        record["unknowns"] = ["Relation interpretation remains unresolved."]
        signal = adapt_art_history_signal(record)
        self.assertEqual({"level": "unknown"}, signal["domain"]["art_history"]["relations"][0]["certainty"])
        self.assertEqual(record["unknowns"], signal["unknowns"])


if __name__ == "__main__":
    unittest.main()
