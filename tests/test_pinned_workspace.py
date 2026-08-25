from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.pinned_workspace import PinnedWorkspaceError, materialize_pinned_workspace


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def make_repo(root: Path) -> tuple[dict, str, str]:
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


class PinnedWorkspaceTests(unittest.TestCase):
    def test_advanced_dirty_and_detached_sources_materialize_the_same_pin(self):
        with tempfile.TemporaryDirectory(prefix="pinned-workspace-") as temporary:
            root = Path(temporary)
            repository, observed, current = make_repo(root / "source" / "child-one")
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
            repository, _observed, _current = make_repo(root / "source" / "child-one")
            repository["observed_commit"] = "0" * 40
            with self.assertRaises(PinnedWorkspaceError) as raised:
                materialize_pinned_workspace({"repositories": [repository]}, root / "source", root / "pinned")
            self.assertIn("observed commit", str(raised.exception))
            self.assertEqual("0" * 40, raised.exception.findings[0]["observed_commit"])
            self.assertEqual("NOT_RUN", raised.exception.findings[0]["materialized_state"])
            self.assertFalse((root / "pinned" / "child-one").exists())

    def test_existing_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory(prefix="pinned-workspace-existing-") as temporary:
            root = Path(temporary)
            repository, _observed, _current = make_repo(root / "source" / "child-one")
            destination = root / "pinned"
            destination.mkdir()
            (destination / "sentinel").write_text("keep\n", encoding="utf-8")
            with self.assertRaisesRegex(PinnedWorkspaceError, "not empty"):
                materialize_pinned_workspace({"repositories": [repository]}, root / "source", destination)
            self.assertEqual("keep\n", (destination / "sentinel").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
