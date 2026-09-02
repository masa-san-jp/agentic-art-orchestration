from __future__ import annotations

import copy
import unittest
from pathlib import Path

from tools.export_signal import ADAPTERS
from tools.signal_bundle import load_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests/fixtures/signal"


class ExportSignalTests(unittest.TestCase):
    def test_each_child_dto_enters_through_its_declared_adapter(self):
        fixtures = {
            "self": "self_adapter_input.json",
            "art-history": "art_adapter_input.json",
            "marketing": "marketing_adapter_input.json",
        }
        for kind, filename in fixtures.items():
            with self.subTest(kind=kind):
                signal = ADAPTERS[kind](load_json(FIXTURE_DIR / filename))
                self.assertEqual(kind, signal["signal_kind"])
                self.assertEqual("normalized-research-signal/v1", signal["contract_version"])

    def test_adapter_boundary_does_not_accept_raw_self_model_payload(self):
        record = load_json(FIXTURE_DIR / "self_adapter_input.json")
        record["raw_voice_body"] = "must never cross the boundary"
        with self.assertRaisesRegex(ValueError, "forbidden raw field"):
            ADAPTERS["self"](record)


if __name__ == "__main__":
    unittest.main()
