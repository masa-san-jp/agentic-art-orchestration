from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.signal_bundle import build_signal_bundle, load_json, validate_signal_bundle


ROOT = Path(__file__).resolve().parents[1]
SIGNAL_DIR = ROOT / "tests/fixtures/signal"


class SignalBundleTests(unittest.TestCase):
    def signals(self) -> list[dict]:
        return [
            load_json(SIGNAL_DIR / name)
            for name in ("valid_self.json", "valid_art_history.json", "valid_marketing.json")
        ]

    def test_bundle_is_versioned_and_keeps_each_repository_commit(self):
        bundle = build_signal_bundle(self.signals(), "2026-08-14T00:00:00+09:00")
        self.assertEqual("normalized-research-signal-bundle/v1", bundle["contract_version"])
        self.assertEqual([], validate_signal_bundle(bundle))
        self.assertEqual(3, len(bundle["records"]))
        self.assertEqual(
            {"self-model", "art-history", "marketing-trends"},
            {item["repository"] for item in bundle["source_repositories"]},
        )

    def test_bundle_is_deterministic_and_sorted_by_signal_id(self):
        signals = self.signals()
        first = build_signal_bundle(signals, "2026-08-14T00:00:00+09:00")
        second = build_signal_bundle(list(reversed(copy.deepcopy(signals))), "2026-08-14T00:00:00+09:00")
        self.assertEqual(first, second)
        self.assertEqual(
            sorted(item["signal_id"] for item in signals),
            [item["signal_id"] for item in first["records"]],
        )

    def test_mixed_commit_for_one_repository_fails_closed(self):
        signals = self.signals()
        changed = copy.deepcopy(signals[0])
        changed["signal_id"] = "self:derived-002"
        changed["source"]["commit"] = "0" * 40
        changed["source"]["entity_ids"] = ["self-entity-002"]
        changed["source"]["locators"] = ["derived/self-entity-002"]
        changed["evidence_refs"][0]["entity_id"] = "self-entity-002"
        with self.assertRaisesRegex(ValueError, "multiple commits"):
            build_signal_bundle(signals + [changed], "2026-08-14T00:00:00+09:00")

    def test_missing_domain_and_unknown_legacy_contract_are_rejected(self):
        bundle = build_signal_bundle(self.signals(), "2026-08-14T00:00:00+09:00")
        bundle["records"] = bundle["records"][:2]
        errors = validate_signal_bundle(bundle, "fixture:missing-marketing")
        self.assertTrue(any("missing signal kinds" in error for error in errors))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(
                json.dumps({"contract_version": "legacy-child-export/v1", "records": self.signals()}),
                encoding="utf-8",
            )
            legacy = load_json(path)
            errors = validate_signal_bundle(legacy, str(path))
            self.assertTrue(any("normalized-research-signal-bundle/v1" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
