from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_TOOL = ROOT / "tools/workspace.py"
CHECKOUT_PATHS = {
    "self-model": "self-model-notes",
    "art-history": "art-history-notes",
    "marketing-trends": "marketing-trends-notes",
    "agentic-art-research": "agentic-art-research",
}


def run_workspace(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WORKSPACE_TOOL), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def run_git(repository: Path, *arguments: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def repository_path(workspace: Path, name: str) -> Path:
    return workspace / CHECKOUT_PATHS.get(name, name)


class WorkspaceGuardTests(unittest.TestCase):
    def make_workspace(self):
        temporary = tempfile.TemporaryDirectory(prefix="workspace-guard-test-")
        root = Path(temporary.name)
        workspace = root / "repos"
        fixture = root / "fixture"
        initialized = run_workspace(
            "init",
            "--offline-fixture",
            "--workspace-root",
            str(workspace),
            "--fixture-root",
            str(fixture),
        )
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        return temporary, workspace, fixture

    def fingerprint(self, repository: Path) -> dict[str, str | None]:
        branch = run_git(repository, "symbolic-ref", "--short", "-q", "HEAD", check=False)
        upstream = run_git(
            repository,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
            check=False,
        )
        return {
            "branch": branch or None,
            "head": run_git(repository, "rev-parse", "HEAD"),
            "origin_head": run_git(repository, "rev-parse", "refs/remotes/origin/main"),
            "remote": run_git(repository, "remote", "get-url", "origin"),
            "status": run_git(repository, "status", "--porcelain", "--untracked-files=all"),
            "upstream": upstream or None,
        }

    def run_guard(self, workspace: Path, fixture: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = run_workspace(
            "guard",
            "--offline-fixture",
            "--json",
            "--workspace-root",
            str(workspace),
            "--fixture-root",
            str(fixture),
        )
        return result, json.loads(result.stdout)

    def assert_blocked_without_mutation(
        self,
        workspace: Path,
        fixture: Path,
        repository_name: str,
        reason_code: str,
        before: dict[str, str | None],
    ) -> None:
        result, payload = self.run_guard(workspace, fixture)
        self.assertEqual(2, result.returncode, result.stderr)
        entry = next(repo for repo in payload["repositories"] if repo["id"] == repository_name)
        self.assertTrue(entry["blocked"])
        self.assertIn(reason_code, entry["reason_codes"])
        self.assertEqual(before, self.fingerprint(repository_path(workspace, repository_name)))

    def commit_local_change(self, repository: Path, filename: str, content: str) -> None:
        (repository / filename).write_text(content, encoding="utf-8")
        run_git(repository, "add", filename)
        result = subprocess.run(
            [
                "git",
                "-c",
                "user.name=guard-test",
                "-c",
                "user.email=guard-test@example.invalid",
                "commit",
                "-m",
                "guard fixture local commit",
            ],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def advance_remote(self, repository: Path, filename: str) -> None:
        remote = run_git(repository, "remote", "get-url", "origin")
        with tempfile.TemporaryDirectory(prefix="workspace-guard-remote-") as temporary:
            seed = Path(temporary) / "seed"
            result = subprocess.run(
                ["git", "clone", remote, str(seed)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            (seed / filename).write_text("remote guard fixture\n", encoding="utf-8")
            run_git(seed, "add", filename)
            result = subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=guard-test",
                    "-c",
                    "user.email=guard-test@example.invalid",
                    "commit",
                    "-m",
                    "guard fixture remote commit",
                ],
                cwd=seed,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            run_git(seed, "push", "origin", "main")

    def test_dirty_checkout_blocks_init_without_mutation(self):
        temporary, workspace, fixture = self.make_workspace()
        try:
            repository = repository_path(workspace, "self-model-notes")
            (repository / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
            before = self.fingerprint(repository)
            result = run_workspace(
                "init",
                "--offline-fixture",
                "--workspace-root",
                str(workspace),
                "--fixture-root",
                str(fixture),
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("dirty", result.stderr)
            self.assertEqual(before, self.fingerprint(repository))
        finally:
            temporary.cleanup()

    def test_dirty_checkout_guard_blocks_without_mutation(self):
        temporary, workspace, fixture = self.make_workspace()
        try:
            repository = repository_path(workspace, "self-model-notes")
            (repository / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
            self.assert_blocked_without_mutation(
                workspace, fixture, "self-model", "dirty", self.fingerprint(repository)
            )
        finally:
            temporary.cleanup()

    def test_detached_checkout_guard_blocks_without_mutation(self):
        temporary, workspace, fixture = self.make_workspace()
        try:
            repository = repository_path(workspace, "art-history-notes")
            run_git(repository, "checkout", "--detach", "HEAD")
            self.assert_blocked_without_mutation(
                workspace, fixture, "art-history", "detached", self.fingerprint(repository)
            )
        finally:
            temporary.cleanup()

    def test_remote_mismatch_guard_blocks_without_mutation(self):
        temporary, workspace, fixture = self.make_workspace()
        try:
            repository = repository_path(workspace, "marketing-trends-notes")
            run_git(repository, "remote", "set-url", "origin", str(Path(temporary.name) / "wrong.git"))
            self.assert_blocked_without_mutation(
                workspace, fixture, "marketing-trends", "remote-mismatch", self.fingerprint(repository)
            )
        finally:
            temporary.cleanup()

    def test_unpushed_checkout_guard_blocks_without_mutation(self):
        temporary, workspace, fixture = self.make_workspace()
        try:
            repository = repository_path(workspace, "agentic-art-research")
            self.commit_local_change(repository, "local.txt", "unpushed\n")
            self.assert_blocked_without_mutation(
                workspace, fixture, "agentic-art-research", "unpushed", self.fingerprint(repository)
            )
        finally:
            temporary.cleanup()

    def test_behind_checkout_guard_blocks_without_mutation(self):
        temporary, workspace, fixture = self.make_workspace()
        try:
            repository = repository_path(workspace, "self-model-notes")
            self.advance_remote(repository, "remote-only.txt")
            run_git(repository, "fetch", "origin")
            self.assert_blocked_without_mutation(
                workspace, fixture, "self-model", "behind", self.fingerprint(repository)
            )
        finally:
            temporary.cleanup()

    def test_diverged_checkout_guard_blocks_without_mutation(self):
        temporary, workspace, fixture = self.make_workspace()
        try:
            repository = repository_path(workspace, "art-history-notes")
            self.commit_local_change(repository, "local-only.txt", "local\n")
            self.advance_remote(repository, "remote-only.txt")
            run_git(repository, "fetch", "origin")
            self.assert_blocked_without_mutation(
                workspace, fixture, "art-history", "diverged", self.fingerprint(repository)
            )
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
