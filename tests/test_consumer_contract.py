from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.consumer import ConsumerCompatibilityError, import_signals


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests/fixtures/signal"


def load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class ConsumerContractTests(unittest.TestCase):
    def test_consumer_imports_all_domain_signals_and_records_provenance(self):
        signals = [
            load_fixture("valid_self.json"),
            load_fixture("valid_art_history.json"),
            load_fixture("valid_marketing.json"),
        ]
        before = copy.deepcopy(signals)
        package = import_signals(signals)

        self.assertEqual(before, signals)
        self.assertEqual("normalized-research-signal/v1", package["contract_version"])
        self.assertEqual(3, len(package["signals"]))
        self.assertEqual(3, len(package["provenance"]))
        for signal, provenance in zip(package["signals"], package["provenance"]):
            self.assertEqual(signal["signal_id"], provenance["signal_id"])
            self.assertEqual(signal["source"]["commit"], provenance["source_commit"])
            self.assertEqual(signal["source"]["repository"], provenance["source_repository"])
            self.assertIn("unknowns", signal)
            self.assertIn("constraints", signal)
            self.assertIn("domain", signal)

    def test_major_version_mismatch_is_rejected(self):
        signal = load_fixture("valid_self.json")
        signal["contract_version"] = "normalized-research-signal/v2"
        with self.assertRaisesRegex(ConsumerCompatibilityError, "major version.*remediation"):
            import_signals([signal])

    def test_minor_extension_is_ignored_without_losing_known_fields(self):
        signal = load_fixture("valid_marketing.json")
        signal["minor_extension"] = {"future_field": "consumer must ignore this"}
        package = import_signals([signal])

        imported = package["signals"][0]
        self.assertNotIn("minor_extension", imported)
        self.assertEqual(signal["signal_id"], imported["signal_id"])
        self.assertEqual(signal["unknowns"], imported["unknowns"])
        self.assertEqual(signal["constraints"], imported["constraints"])
        self.assertEqual(signal["domain"], imported["domain"])

    def test_invalid_signal_is_rejected_before_import(self):
        signal = load_fixture("valid_art_history.json")
        signal["source"]["commit"] = "not-a-commit"
        with self.assertRaisesRegex(ConsumerCompatibilityError, "source.commit.*remediation"):
            import_signals([signal])

    def test_duplicate_signal_id_is_rejected(self):
        first = load_fixture("valid_self.json")
        second = load_fixture("valid_self.json")
        second["source"]["commit"] = "0" * 40
        with self.assertRaisesRegex(ConsumerCompatibilityError, "duplicate signal_id.*remediation"):
            import_signals([first, second])


if __name__ == "__main__":
    unittest.main()
