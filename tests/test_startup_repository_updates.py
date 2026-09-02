from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.validate import load_yaml


ROOT = Path(__file__).resolve().parents[1]
STARTUP_TOOL = ROOT / "tools/startup.py"


def git(cwd: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def run_startup(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(STARTUP_TOOL), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class StartupRepositoryUpdateTests(unittest.TestCase):
    def test_offline_startup_reports_all_pins_without_mutating_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="startup-update-test-") as temporary:
            root = Path(temporary)
            fixture = root / "fixture"
            output = root / "startup.json"
            snapshot = ROOT / "data/snapshot.json"
            before = snapshot.read_bytes()

            materialize = run_startup(
                "--offline-fixture",
                "--fixture-root",
                str(fixture),
                "--snapshot",
                str(snapshot),
                "--output",
                str(output),
                "--run-id",
                "startup-update-fixture",
            )
            self.assertEqual(0, materialize.returncode, materialize.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("READY_WITH_FINDINGS", report["status"])
            manifest = load_yaml(ROOT / "config/repositories.yaml")
            self.assertEqual(len(manifest["repositories"]), len(report["repositories"]))
            self.assertTrue(all(record["pinned_for_use"] for record in report["repositories"]))
            self.assertEqual("PASSED", report["workspace_guard"]["status"])
            self.assertEqual([], report["remote_operations"])
            self.assertEqual(before, snapshot.read_bytes())

            checked = run_startup(
                "--check",
                "--offline-fixture",
                "--fixture-root",
                str(fixture),
                "--snapshot",
                str(snapshot),
                "--output",
                str(output),
                "--run-id",
                "startup-update-fixture",
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            self.assertIn('"changed": false', checked.stdout)

    def test_remote_observation_distinguishes_clean_update_and_unavailable(self):
        spec = __import__("importlib.util").util.spec_from_file_location("startup_tool", STARTUP_TOOL)
        module = __import__("importlib.util").util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="startup-remote-test-") as temporary:
            root = Path(temporary)
            seed = root / "seed"
            remote = root / "remote.git"
            git(root, "init", "-b", "main", str(seed))
            (seed / "README.md").write_text("remote fixture\n", encoding="utf-8")
            git(seed, "add", "README.md")
            git(seed, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "initial")
            git(root, "init", "--bare", str(remote))
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "origin", "main")
            commit = git(seed, "rev-parse", "HEAD")
            repository = {"id": "synthetic", "default_branch": "main"}
            clean = module.observe_repository(repository, commit, str(remote), "2026-08-13T12:00:00Z")
            self.assertEqual("CLEAN", clean["drift"])
            (seed / "next.txt").write_text("update\n", encoding="utf-8")
            git(seed, "add", "next.txt")
            git(seed, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "update")
            git(seed, "push", "origin", "main")
            update = module.observe_repository(repository, commit, str(remote), "2026-08-13T12:00:00Z")
            self.assertEqual("UPDATE_CANDIDATE", update["drift"])
            unavailable = module.observe_repository(repository, commit, str(root / "missing.git"), "2026-08-13T12:00:00Z")
            self.assertEqual("UNAVAILABLE", unavailable["drift"])
            self.assertTrue(unavailable["pinned_for_use"])

    def test_remote_observation_uses_argument_list_without_shell_controls(self):
        spec = __import__("importlib.util").util.spec_from_file_location("startup_tool", STARTUP_TOOL)
        module = __import__("importlib.util").util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        calls = []
        original = module._run_git

        def capture(args, cwd=None):
            calls.append(args)
            return 0, "a" * 40 + "\trefs/heads/main", ""

        module._run_git = capture
        try:
            module._remote_head("https://example.invalid/repo.git", "main")
        finally:
            module._run_git = original
        self.assertEqual([["ls-remote", "https://example.invalid/repo.git", "refs/heads/main"]], calls)
        self.assertTrue(all(token not in {";", "&&", "||", "|", ">", "<", "`"} for call in calls for token in call))


if __name__ == "__main__":
    unittest.main()
