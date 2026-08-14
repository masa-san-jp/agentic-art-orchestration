from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.input_pipeline import run_input_pipeline
from tools.signal_bundle import build_signal_bundle, validate_signal_bundle


ROOT = Path(__file__).resolve().parents[1]
def fixture_signals() -> list[dict]:
    return [
        json.loads((ROOT / "tests" / "fixtures" / "signal" / name).read_text(encoding="utf-8"))
        for name in ("valid_self.json", "valid_art_history.json", "valid_marketing.json")
    ]


class InputPipelineTests(unittest.TestCase):
    def test_bundle_is_one_canonical_envelope_for_all_input_kbs(self) -> None:
        bundle = build_signal_bundle(fixture_signals(), "2026-08-14T00:00:00+09:00")
        self.assertEqual([], validate_signal_bundle(bundle))
        self.assertEqual(
            ["art-history", "marketing-trends", "self-model"],
            [item["repository"] for item in bundle["source_repositories"]],
        )
        self.assertEqual(3, len(bundle["records"]))

    def test_pipeline_preserves_one_bundle_through_consumer_and_selection(self) -> None:
        bundle = build_signal_bundle(fixture_signals(), "2026-08-14T00:00:00+09:00")
        result = run_input_pipeline(bundle, project_id="pipeline-test", seed_input="default")
        self.assertIs(bundle, result["bundle"])
        self.assertEqual(1, result["selection"]["selected_count"])
        self.assertEqual({"self", "art-history", "marketing"}, {record["signal_kind"] for record in bundle["records"]})
        self.assertEqual(
            sorted(record["signal_id"] for record in bundle["records"]),
            sorted(
                signal["signal_id"]
                for proposition in result["provenance"]["propositions"]
                for signal in proposition["normalized_signals"]
            ),
        )

    def test_bundle_rejects_mixed_commit_for_one_source_repository(self) -> None:
        signals = fixture_signals()
        signals[1]["source"]["repository"] = "self-model"
        signals[1]["source"]["commit"] = "f" * 40
        with self.assertRaises(ValueError):
            build_signal_bundle(signals, "2026-08-14T00:00:00+09:00")

if __name__ == "__main__":
    unittest.main()
