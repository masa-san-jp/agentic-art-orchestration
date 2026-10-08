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
    def content_record(self):
        record = load_input()
        record['relations'] = []
        record['content'] = [{'text': '先送りと時間', 'source_refs': ['https://example.test/source'],
                              'source_locator': record['source_locator'] + '#定義'}]
        record['entity_labels'] = ['合成運動']
        return record

    def test_content_only_signal_retains_native_locator_sources_and_uncertainty(self):
        record = self.content_record()
        record['validity']['status'] = 'unknown'
        before = copy.deepcopy(record)
        signal = adapt_art_history_signal(record)
        self.assertEqual(before, record)
        self.assertEqual(record['content'], signal['domain']['art_history']['content'])
        self.assertEqual('unknown', signal['validity']['status'])
        self.assertIn('https://example.test/source', [ref['locator'] for ref in signal['evidence_refs']])
        signal['domain']['art_history']['content'][0]['text'] = '変更'
        self.assertEqual(before, record)

    def test_content_rejects_missing_sources_wrong_locator_and_over_limit(self):
        for field, value in (('source_refs', []), ('source_refs', ['not-a-source']),
                             ('source_locator', 'another.md#定義'), ('text', 'x' * 2401), ('text', ' ')):
            with self.subTest(field=field, value=str(value)[:30]):
                record = self.content_record()
                record['content'][0][field] = value
                with self.assertRaises(AdapterError):
                    adapt_art_history_signal(record)
        record = self.content_record()
        record['content'] *= 2
        record['content'][0]['text'] = 'x' * 1201
        with self.assertRaises(AdapterError):
            adapt_art_history_signal(record)

    def test_content_urls_must_be_retained_in_normalized_evidence(self):
        signal = adapt_art_history_signal(self.content_record())
        signal['evidence_refs'] = [ref for ref in signal['evidence_refs'] if ref['locator'] != 'https://example.test/source']
        self.assertTrue(validate_signal(signal, 'content-evidence'))

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
