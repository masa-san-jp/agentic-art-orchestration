from __future__ import annotations

import tempfile
import subprocess
import unittest
from pathlib import Path

import yaml

from tools.pinned_workspace import (
    MANIFEST,
    PinnedWorkspaceError,
    WorkspaceError,
    _authenticated,
    _redacted,
    _selected_repositories,
    materialize,
    materialize_pinned_workspace,
)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def make_local_repo(root: Path) -> tuple[dict, str, str]:
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "marker.txt").write_text("observed\n", encoding="utf-8")
    git(root, "add", "marker.txt")
    git(root, "commit", "-q", "-m", "observed")
    observed = git(root, "rev-parse", "HEAD")
    (root / "marker.txt").write_text("current\n", encoding="utf-8")
    git(root, "add", "marker.txt")
    git(root, "commit", "-q", "-m", "current")
    current = git(root, "rev-parse", "HEAD")
    return {
        "id": "child-one",
        "path": "child-one",
        "observed_commit": observed,
        "quality_gates": ["python3 -c 'print(\"ok\")'"],
    }, observed, current


class AuthenticatedRemoteTests(unittest.TestCase):
    def test_token_is_injected_for_github_https_remotes(self) -> None:
        url = _authenticated("https://github.com/owner/repo.git", "secret-token")

        self.assertEqual(url, "https://x-access-token:secret-token@github.com/owner/repo.git")

    def test_url_is_unchanged_without_a_token(self) -> None:
        url = _authenticated("https://github.com/owner/repo.git", None)

        self.assertEqual(url, "https://github.com/owner/repo.git")

    def test_non_github_remote_never_receives_the_token(self) -> None:
        url = _authenticated("/tmp/offline-fixture/remotes/child.git", "secret-token")

        self.assertNotIn("secret-token", url)


class RedactionTests(unittest.TestCase):
    def test_token_is_removed_from_reported_output(self) -> None:
        text = _redacted("fatal: could not read https://x-access-token:secret@github.com/o/r", "secret")

        self.assertNotIn("secret", text)

    def test_output_is_unchanged_without_a_token(self) -> None:
        self.assertEqual(_redacted("fatal: repository not found", None), "fatal: repository not found")


class MaterializeGuardTests(unittest.TestCase):
    def test_repository_selection_is_explicit_and_defaults_to_all(self) -> None:
        manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
        all_repositories = _selected_repositories(manifest, None)
        selected = _selected_repositories(manifest, ["agentic-art-research", "agentic-art-production"])

        self.assertEqual(len(manifest["repositories"]), len(all_repositories))
        self.assertEqual(
            ["agentic-art-research", "agentic-art-production"],
            [repository["id"] for repository in selected],
        )

    def test_unknown_repository_selection_fails_closed(self) -> None:
        manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))

        with self.assertRaisesRegex(WorkspaceError, "unknown repository"):
            _selected_repositories(manifest, ["viewer-response-notes", "not-in-manifest"])

    def test_existing_destination_is_rejected_before_cloning(self) -> None:
        manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
        first = manifest["repositories"][0]["path"]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "workspace"
            (output / first).mkdir(parents=True)

            with self.assertRaises(WorkspaceError) as raised:
                materialize(output, None)

        self.assertIn("already exists", str(raised.exception))

    def test_every_manifest_entry_declares_a_full_commit(self) -> None:
        manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))

        for repository in manifest["repositories"]:
            with self.subTest(repository=repository["id"]):
                self.assertRegex(str(repository["observed_commit"]), r"^[0-9a-f]{40}$")


class LocalPinnedWorkspaceTests(unittest.TestCase):
    def test_advanced_dirty_and_detached_sources_materialize_the_same_pin(self):
        with tempfile.TemporaryDirectory(prefix="pinned-workspace-") as temporary:
            root = Path(temporary)
            repository, observed, current = make_local_repo(root / "source" / "child-one")
            source = root / "source"
            before_head = git(source / "child-one", "rev-parse", "HEAD")
            first = materialize_pinned_workspace({"repositories": [repository]}, source, root / "pinned-advanced")
            self.assertEqual("STALE", first[0]["source_state"])
            self.assertEqual(current, first[0]["source_head"])
            self.assertEqual(observed, git(root / "pinned-advanced" / "child-one", "rev-parse", "HEAD"))
            self.assertEqual("observed\n", (root / "pinned-advanced" / "child-one" / "marker.txt").read_text(encoding="utf-8"))

            (source / "child-one" / "dirty.txt").write_text("do not copy\n", encoding="utf-8")
            second = materialize_pinned_workspace({"repositories": [repository]}, source, root / "pinned-dirty")
            self.assertEqual("DIRTY", second[0]["source_state"])
            self.assertFalse((root / "pinned-dirty" / "child-one" / "dirty.txt").exists())
            self.assertEqual(observed, git(root / "pinned-dirty" / "child-one", "rev-parse", "HEAD"))

            git(source / "child-one", "clean", "-q", "-fd")
            git(source / "child-one", "checkout", "-q", "--detach", observed)
            third = materialize_pinned_workspace({"repositories": [repository]}, source, root / "pinned-detached")
            self.assertEqual("DETACHED", third[0]["source_state"])
            self.assertEqual(observed, git(root / "pinned-detached" / "child-one", "rev-parse", "HEAD"))
            self.assertEqual(before_head, current)
            self.assertEqual(observed, git(source / "child-one", "rev-parse", "HEAD"))

    def test_unavailable_observed_commit_fails_closed_with_exact_pin_finding(self):
        with tempfile.TemporaryDirectory(prefix="pinned-workspace-missing-") as temporary:
            root = Path(temporary)
            repository, _observed, _current = make_local_repo(root / "source" / "child-one")
            repository["observed_commit"] = "0" * 40
            with self.assertRaises(PinnedWorkspaceError) as raised:
                materialize_pinned_workspace({"repositories": [repository]}, root / "source", root / "pinned")
            self.assertIn("observed commit", str(raised.exception))
            self.assertEqual("0" * 40, raised.exception.findings[0]["observed_commit"])
            self.assertEqual("NOT_RUN", raised.exception.findings[0]["materialized_state"])
            self.assertFalse((root / "pinned" / "child-one").exists())

    def test_existing_destination_is_not_overwritten_by_local_materialization(self):
        with tempfile.TemporaryDirectory(prefix="pinned-workspace-existing-") as temporary:
            root = Path(temporary)
            repository, _observed, _current = make_local_repo(root / "source" / "child-one")
            destination = root / "pinned"
            destination.mkdir()
            (destination / "sentinel").write_text("keep\n", encoding="utf-8")
            with self.assertRaisesRegex(PinnedWorkspaceError, "not empty"):
                materialize_pinned_workspace({"repositories": [repository]}, root / "source", destination)
            self.assertEqual("keep\n", (destination / "sentinel").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
