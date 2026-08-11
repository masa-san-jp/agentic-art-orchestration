from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.adapters import AdapterError, adapt_marketing_signal
from tools.validate import validate_signal


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/signal/marketing_adapter_input.json"


def load_input() -> dict:
    with FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


class MarketingAdapterTests(unittest.TestCase):
    def test_current_trend_preserves_machine_checkable_marketing_fields(self):
        record = load_input()
        before = copy.deepcopy(record)
        signal = adapt_marketing_signal(record)

        self.assertEqual(before, record)
        self.assertEqual([], validate_signal(signal, "fixture:marketing-adapter"))
        marketing = signal["domain"]["marketing"]
        self.assertEqual(record["stage"], marketing["stage"])
        self.assertEqual(record["freshness"]["status"], marketing["freshness"])
        self.assertEqual(record["retrieved"], marketing["retrieved"])
        self.assertEqual(record["vendor_interest"], marketing["vendor_interest"])
        self.assertEqual(record["counterevidence"], marketing["counterevidence"])
        self.assertEqual(record["revalidate_at"], marketing["revalidate_at"])
        self.assertEqual(record["expires_at"], marketing["expires_at"])
        self.assertEqual(record["commit"], signal["source"]["commit"])

    def test_stale_signal_is_retained_as_constraint_and_not_verified(self):
        record = load_input()
        record["freshness"] = {
            "status": "stale",
            "retrieved_at": "2026-01-01T15:00:00+09:00",
            "revalidate_at": "2026-02-01T15:00:00+09:00",
        }
        record["validity"]["status"] = "stale"
        record["revalidate_at"] = "2026-02-01T15:00:00+09:00"
        record["constraints"] = ["This signal is stale and must be revalidated."]
        record["prediction_status"] = "pending"
        signal = adapt_marketing_signal(record)
        self.assertEqual("stale", signal["freshness"]["status"])
        self.assertEqual("stale", signal["validity"]["status"])
        self.assertEqual("pending", signal["domain"]["marketing"]["prediction_status"])
        self.assertIn("stale", signal["constraints"][0])

    def test_stale_signal_cannot_be_marked_confirmed(self):
        record = load_input()
        record["freshness"]["status"] = "stale"
        record["validity"]["status"] = "stale"
        record["constraints"] = ["This signal is stale and must be revalidated."]
        record["prediction_status"] = "confirmed"
        with self.assertRaisesRegex(AdapterError, "stale.*confirmed.*remediation"):
            adapt_marketing_signal(record)

    def test_anecdotal_evidence_cannot_be_marked_confirmed(self):
        record = load_input()
        record["evidence_kind"] = "anecdotal"
        record["prediction_status"] = "confirmed"
        with self.assertRaisesRegex(AdapterError, "anecdotal.*confirmed.*remediation"):
            adapt_marketing_signal(record)

    def test_retrieval_and_revalidation_are_required_and_consistent(self):
        for field in ("retrieved", "revalidate_at", "expires_at", "counterevidence"):
            with self.subTest(field=field):
                record = load_input()
                del record[field]
                with self.assertRaisesRegex(AdapterError, "required input field"):
                    adapt_marketing_signal(record)
        record = load_input()
        record["revalidate_at"] = "2026-09-01T15:00:00+09:00"
        with self.assertRaisesRegex(AdapterError, "revalidate_at.*remediation"):
            adapt_marketing_signal(record)


if __name__ == "__main__":
    unittest.main()
