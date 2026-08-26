from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.input_pipeline import run_input_pipeline
from tools.run import run
from tools.signal_bundle import build_signal_bundle


ROOT = Path(__file__).resolve().parents[1]


def fixture_signals() -> list[dict]:
    return [
        json.loads((ROOT / "tests" / "fixtures" / "signal" / name).read_text(encoding="utf-8"))
        for name in ("valid_self.json", "valid_art_history.json", "valid_marketing.json")
    ]


class RunTests(unittest.TestCase):
    def bundle(self) -> dict:
        return build_signal_bundle(fixture_signals(), "2026-08-26T00:00:00+09:00")

    def test_no_intent_keeps_the_existing_v1_selection_contract(self) -> None:
        bundle = self.bundle()
        legacy = run_input_pipeline(bundle, project_id="run-test", seed_input="seed")
        current = run(bundle, project_id="run-test", seed_input="seed")
        self.assertEqual("research-selection/v1", current["selection"]["contract_version"])
        self.assertEqual(legacy["selection"], current["selection"])
        self.assertNotIn("intent_sha256", current)

    def test_intent_is_passed_to_selection_and_only_digest_is_exposed(self) -> None:
        raw_intent = "A private phrase only used for this test"
        result = run(self.bundle(), project_id="run-test", seed_input="seed", intent=raw_intent)
        self.assertEqual("research-selection/v2", result["selection"]["contract_version"])
        self.assertEqual("intent-rank/v1", result["intent_algorithm"])
        self.assertEqual(result["intent_sha256"], result["selection"]["intent_sha256"])
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(raw_intent, rendered)
        self.assertNotIn("\"intent\":", rendered)
        for candidate in result["selection"]["selected_candidates"]:
            self.assertIn("intent_score", candidate)
            self.assertIn("intent_kind_scores", candidate)

    def test_cli_digest_matches_selection_and_log_does_not_contain_raw_intent(self) -> None:
        raw_intent = "CLI-only phrase with private wording"
        with tempfile.TemporaryDirectory(prefix="run-intent-test-") as temporary:
            temporary_root = Path(temporary)
            bundle_path = temporary_root / "bundle.json"
            output_path = temporary_root / "run.json"
            bundle_path.write_text(json.dumps(self.bundle(), ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "run.py"),
                    "--bundle",
                    str(bundle_path),
                    "--project-id",
                    "run-test",
                    "--seed-input",
                    "seed",
                    "--intent",
                    raw_intent,
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertNotIn(raw_intent, completed.stdout + completed.stderr)
            summary = json.loads(completed.stdout)
            output = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["intent_sha256"], output["intent_sha256"])
            self.assertEqual(summary["intent_sha256"], output["selection"]["intent_sha256"])
            self.assertEqual("intent-rank/v1", summary["intent_algorithm"])


if __name__ == "__main__":
    unittest.main()
