from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.trace import build_trace


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/portfolio"
TRACE_TOOL = ROOT / "tools/trace.py"


class TraceTests(unittest.TestCase):
    def test_trace_check_builds_requirement_to_source_edges(self):
        result = subprocess.run(
            [sys.executable, str(TRACE_TOOL), "--check", "--fixture", str(FIXTURE)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        trace = json.loads(result.stdout)
        self.assertEqual(1, trace["version"])
        self.assertEqual(3, len(trace["requirements"]))
        self.assertEqual(3, trace["signal_count"])
        for requirement in trace["requirements"]:
            self.assertTrue(requirement["edges"])
            for edge in requirement["edges"]:
                self.assertRegex(edge["source_commit"], r"^[0-9a-f]{40}$")
                self.assertTrue(edge["source_entity_ids"])
                self.assertTrue(edge["source_locators"])
                self.assertTrue(edge["evidence_locators"])
        self.assertEqual(64, len(trace["trace_hash"]))

    def test_trace_is_deterministic(self):
        first, first_errors = build_trace(FIXTURE)
        second, second_errors = build_trace(FIXTURE)
        self.assertEqual([], first_errors)
        self.assertEqual([], second_errors)
        self.assertEqual(first, second)

    def test_unlinked_requirement_fails(self):
        with tempfile.TemporaryDirectory(prefix="trace-invalid-") as temporary:
            root = Path(temporary)
            portfolio = json.loads((FIXTURE / "portfolio.json").read_text(encoding="utf-8"))
            signal_dir = root / "signal"
            signal_dir.mkdir()
            for relative in ("valid_self.json", "valid_art_history.json", "valid_marketing.json"):
                source = FIXTURE.parent / "signal" / relative
                (signal_dir / relative).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            portfolio["signal_files"] = ["signal/valid_self.json", "signal/valid_art_history.json", "signal/valid_marketing.json"]
            portfolio["requirements"][0]["signal_ids"] = ["missing-signal"]
            (root / "portfolio.json").write_text(json.dumps(portfolio), encoding="utf-8")
            trace, errors = build_trace(root)
            self.assertIsNone(trace)
            self.assertTrue(any("unknown 'missing-signal'" in error for error in errors))

    def test_signal_source_commit_failure_blocks_trace(self):
        with tempfile.TemporaryDirectory(prefix="trace-invalid-signal-") as temporary:
            root = Path(temporary)
            portfolio = json.loads((FIXTURE / "portfolio.json").read_text(encoding="utf-8"))
            signal_dir = root / "signal"
            signal_dir.mkdir()
            for relative in ("valid_self.json", "valid_art_history.json", "valid_marketing.json"):
                payload = json.loads((FIXTURE.parent / "signal" / relative).read_text(encoding="utf-8"))
                if relative == "valid_self.json":
                    payload["source"]["commit"] = "invalid"
                (signal_dir / relative).write_text(json.dumps(payload), encoding="utf-8")
            portfolio["signal_files"] = ["signal/valid_self.json", "signal/valid_art_history.json", "signal/valid_marketing.json"]
            (root / "portfolio.json").write_text(json.dumps(portfolio), encoding="utf-8")
            trace, errors = build_trace(root)
            self.assertIsNone(trace)
            self.assertTrue(any("source.commit" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
