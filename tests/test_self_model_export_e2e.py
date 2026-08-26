from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

from tools.adapters import adapt_self_model_signal
from tools.consumer import import_signals
from tools.validate import validate_signal


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/signal/self_export_bundle.json"
SOURCE_COMMIT = "04095bfa4115ef4fde8a8f475bf31743ecdff962"
FIXED_RECORD_FIELDS = {
    "signal_id",
    "repository",
    "commit",
    "entity_id",
    "source_locator",
    "evidence_locator",
    "evidence_kind",
    "statement",
    "certainty",
    "unknowns",
    "constraints",
    "validity",
    "freshness",
    "generated_at",
    "adapter_version",
    "consent_scope",
    "export_permitted",
    "seeks",
    "protects",
    "avoids",
    "tensions",
    "recurring_patterns",
    "raw_voice_locator",
    "traits",
    "states",
    "contexts",
}
DOMAIN_FIELDS = {
    "consent_scope",
    "export_permitted",
    "seeks",
    "protects",
    "avoids",
    "tensions",
    "recurring_patterns",
    "raw_voice_locator",
    "traits",
    "states",
    "contexts",
}


def load_bundle() -> dict:
    with FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


class SelfModelExportE2ETests(unittest.TestCase):
    def test_fixture_is_the_pinned_child_envelope(self):
        bundle = load_bundle()

        self.assertEqual(bundle["contract_version"], "research-signal-export/v1")
        self.assertEqual(bundle["source_repository"], "self-model")
        self.assertEqual(bundle["source_commit"], SOURCE_COMMIT)
        self.assertEqual(bundle["signal_count"], len(bundle["signals"]))
        self.assertGreater(bundle["signal_count"], 0)

        signal_ids = [record["signal_id"] for record in bundle["signals"]]
        self.assertEqual(signal_ids, sorted(signal_ids))
        self.assertEqual(len(signal_ids), len(set(signal_ids)))
        for record in bundle["signals"]:
            self.assertEqual(record["commit"], SOURCE_COMMIT)
            self.assertEqual(record["repository"], "self-model")
            self.assertEqual(set(record), FIXED_RECORD_FIELDS)

    def test_every_record_passes_adapter_and_preserves_domain_and_provenance(self):
        bundle = load_bundle()
        normalized = []

        for record in bundle["signals"]:
            signal = adapt_self_model_signal(record)
            normalized.append(signal)
            self.assertEqual(validate_signal(signal, f"fixture:{record['signal_id']}"), [])
            self.assertEqual(signal["signal_id"], record["signal_id"])
            self.assertEqual(signal["source"]["repository"], "self-model")
            self.assertEqual(signal["source"]["commit"], SOURCE_COMMIT)
            self.assertEqual(signal["source"]["entity_ids"], [record["entity_id"]])
            self.assertEqual(signal["source"]["locators"], [record["source_locator"]])
            self.assertEqual(signal["evidence_refs"], [{
                "locator": record["evidence_locator"],
                "kind": record["evidence_kind"],
                "entity_id": record["entity_id"],
            }])
            self.assertEqual(signal["certainty"], record["certainty"])
            self.assertEqual(signal["unknowns"], record["unknowns"])
            self.assertEqual(signal["constraints"], record["constraints"])
            self.assertEqual(signal["validity"], record["validity"])
            self.assertEqual(signal["freshness"], record["freshness"])
            self.assertEqual(signal["domain"]["self_model"], {
                field: record[field] for field in DOMAIN_FIELDS
            })

        self.assertEqual(len(normalized), bundle["signal_count"])

    def test_consumer_imports_all_records_without_count_or_provenance_drift(self):
        bundle = load_bundle()
        records = copy.deepcopy(bundle["signals"])
        normalized = [adapt_self_model_signal(record) for record in records]
        package = import_signals(normalized)

        self.assertEqual(package["contract_version"], "normalized-research-signal/v1")
        self.assertEqual(len(records), len(normalized))
        self.assertEqual(len(normalized), len(package["signals"]))
        self.assertEqual(len(normalized), len(package["provenance"]))
        self.assertEqual(
            [signal["signal_id"] for signal in normalized],
            [signal["signal_id"] for signal in package["signals"]],
        )

        for source, imported, provenance in zip(normalized, package["signals"], package["provenance"]):
            for field in (
                "signal_id", "statement", "certainty", "unknowns", "constraints",
                "validity", "freshness", "domain",
            ):
                self.assertEqual(source[field], imported[field], field)
            self.assertEqual(source["source"], imported["source"])
            self.assertEqual(provenance, {
                "signal_id": source["signal_id"],
                "source_repository": "self-model",
                "source_commit": SOURCE_COMMIT,
            })

    def test_fixture_and_transformed_outputs_have_only_opaque_self_locators(self):
        bundle = load_bundle()
        normalized = [adapt_self_model_signal(record) for record in bundle["signals"]]
        imported = import_signals(normalized)
        serialized = json.dumps(
            {"fixture": bundle, "normalized": normalized, "imported": imported},
            ensure_ascii=False,
        ).lower()

        for forbidden in ("raw_voice_body", "raw_voice_text", "direct_identifier", "private_raw", "restricted", "gdrive://", "telegram"):
            self.assertNotIn(forbidden, serialized)
        for signal in normalized:
            self.assertRegex(
                signal["domain"]["self_model"]["raw_voice_locator"],
                r"^self-model://[^\s]+#raw-voice-not-exported$",
            )
            self.assertTrue(all(locator.startswith("self-model://") for locator in signal["source"]["locators"]))
            self.assertTrue(all(ref["locator"].startswith("self-model://") for ref in signal["evidence_refs"]))

        self.assertNotRegex(serialized, re.compile(r"(?:^|[^a-z])(token|password|secret)(?:[^a-z]|$)"))

    def test_input_records_are_not_mutated_by_adapter_or_consumer(self):
        bundle = load_bundle()
        records = copy.deepcopy(bundle["signals"])
        before = copy.deepcopy(records)
        normalized = [adapt_self_model_signal(record) for record in records]
        import_signals(normalized)
        self.assertEqual(records, before)


if __name__ == "__main__":
    unittest.main()
