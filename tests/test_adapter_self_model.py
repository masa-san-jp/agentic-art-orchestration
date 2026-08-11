from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.adapters import AdapterError, adapt_self_model_signal
from tools.validate import validate_signal


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/signal/self_adapter_input.json"


def load_input() -> dict:
    with FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


class SelfModelAdapterTests(unittest.TestCase):
    def test_approved_derived_record_exports_valid_signal(self):
        record = load_input()
        before = copy.deepcopy(record)
        signal = adapt_self_model_signal(record)

        self.assertEqual(before, record)
        self.assertEqual([], validate_signal(signal, "fixture:self-adapter"))
        self.assertEqual("self-model", signal["source"]["repository"])
        self.assertEqual(record["commit"], signal["source"]["commit"])
        self.assertEqual([record["evidence_locator"]], [ref["locator"] for ref in signal["evidence_refs"]])
        self.assertEqual(record["certainty"], signal["certainty"])
        self.assertNotIn("raw_voice", signal["domain"]["self_model"])
        self.assertEqual(record["raw_voice_locator"], signal["domain"]["self_model"]["raw_voice_locator"])

    def test_consent_violation_is_rejected_before_export(self):
        record = load_input()
        record["export_permitted"] = False
        with self.assertRaisesRegex(AdapterError, "export_permitted.*remediation"):
            adapt_self_model_signal(record)

    def test_raw_voice_body_is_rejected_and_never_copied(self):
        record = load_input()
        record["raw_voice_body"] = "synthetic raw voice must remain in the child repository"
        with self.assertRaisesRegex(AdapterError, "raw field.*remediation"):
            adapt_self_model_signal(record)

    def test_missing_provenance_or_evidence_is_rejected(self):
        for field in ("commit", "evidence_locator", "raw_voice_locator"):
            with self.subTest(field=field):
                record = load_input()
                del record[field]
                with self.assertRaisesRegex(AdapterError, "required input field"):
                    adapt_self_model_signal(record)

    def test_unknown_and_freshness_are_forwarded_without_normalization(self):
        record = load_input()
        record["certainty"] = {"level": "unknown"}
        record["unknowns"] = ["The child source does not establish this claim."]
        record["freshness"] = {
            "status": "unknown",
            "retrieved_at": "2026-08-11T15:00:00+09:00",
            "revalidate_at": "2026-09-11T15:00:00+09:00",
        }
        signal = adapt_self_model_signal(record)
        self.assertEqual("unknown", signal["certainty"]["level"])
        self.assertEqual("unknown", signal["freshness"]["status"])
        self.assertEqual(record["unknowns"], signal["unknowns"])


if __name__ == "__main__":
    unittest.main()
