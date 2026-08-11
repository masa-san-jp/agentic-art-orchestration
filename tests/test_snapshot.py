from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_TOOL = ROOT / "tools/workspace.py"


def run_workspace(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WORKSPACE_TOOL), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


class SnapshotTests(unittest.TestCase):
    def initialize(self, root: Path) -> tuple[Path, Path, Path]:
        workspace = root / "repos"
        fixture = root / "fixture"
        output = root / "data"
        result = run_workspace(
            "init",
            "--offline-fixture",
            "--workspace-root",
            str(workspace),
            "--fixture-root",
            str(fixture),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return workspace, fixture, output

    def snapshot(self, workspace: Path, fixture: Path, output: Path, *extra: str):
        result = run_workspace(
            "snapshot",
            "--workspace-root",
            str(workspace),
            "--fixture-root",
            str(fixture),
            "--output-dir",
            str(output),
            *extra,
        )
        return result

    def test_check_is_reproducible_before_and_after_materialization(self):
        with tempfile.TemporaryDirectory(prefix="snapshot-test-") as temporary:
            workspace, fixture, output = self.initialize(Path(temporary))
            before = self.snapshot(workspace, fixture, output, "--check")
            self.assertEqual(0, before.returncode, before.stderr)
            self.assertFalse(json.loads(before.stdout)["files_present"])

            first = self.snapshot(workspace, fixture, output)
            self.assertEqual(0, first.returncode, first.stderr)
            first_result = json.loads(first.stdout)
            self.assertTrue(first_result["changed"])
            snapshot_json = output / "snapshot.json"
            snapshot_markdown = output / "snapshot.md"
            first_json_bytes = snapshot_json.read_bytes()
            first_markdown_bytes = snapshot_markdown.read_bytes()
            payload = json.loads(first_json_bytes)
            self.assertEqual(4, len(payload["repositories"]))
            self.assertRegex(payload["captured_at"], r"Z$")
            self.assertEqual(first_result["snapshot_hash"], payload["snapshot_hash"])
            for repository in payload["repositories"]:
                self.assertIn("head", repository)
                self.assertIn("branch", repository)
                self.assertIn("upstream", repository)
                self.assertIn("dirty", repository)
                self.assertIn("detached", repository)
                self.assertIn("ahead", repository)
                self.assertIn("behind", repository)
                self.assertIn("requirement_ssot", repository)
                self.assertIn("contract", repository)
                self.assertIn("quality_gate_hash", repository)

            second = self.snapshot(workspace, fixture, output)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertFalse(json.loads(second.stdout)["changed"])
            self.assertEqual(first_json_bytes, snapshot_json.read_bytes())
            self.assertEqual(first_markdown_bytes, snapshot_markdown.read_bytes())

            checked = self.snapshot(workspace, fixture, output, "--check")
            self.assertEqual(0, checked.returncode, checked.stderr)
            self.assertTrue(json.loads(checked.stdout)["files_present"])

    def test_snapshot_records_dirty_and_detached_state(self):
        with tempfile.TemporaryDirectory(prefix="snapshot-state-test-") as temporary:
            workspace, fixture, output = self.initialize(Path(temporary))
            repository = workspace / "self-model-notes"
            (repository / "uncommitted.txt").write_text("fixture\n", encoding="utf-8")
            run_git(repository, "checkout", "--detach", "HEAD")
            result = self.snapshot(workspace, fixture, output)
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads((output / "snapshot.json").read_text(encoding="utf-8"))
            state = next(item for item in payload["repositories"] if item["id"] == "self-model")
            self.assertTrue(state["dirty"])
            self.assertTrue(state["untracked"])
            self.assertTrue(state["detached"])
            self.assertIsNone(state["branch"])
            self.assertEqual("dirty", state["state"])

    def test_check_rejects_stale_materialized_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="snapshot-stale-test-") as temporary:
            workspace, fixture, output = self.initialize(Path(temporary))
            generated = self.snapshot(workspace, fixture, output)
            self.assertEqual(0, generated.returncode, generated.stderr)
            snapshot_json = output / "snapshot.json"
            payload = json.loads(snapshot_json.read_text(encoding="utf-8"))
            payload["captured_at"] = "1970-01-01T00:00:00Z"
            snapshot_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            checked = self.snapshot(workspace, fixture, output, "--check")
            self.assertNotEqual(0, checked.returncode)
            self.assertIn("stale", checked.stderr)


if __name__ == "__main__":
    unittest.main()
