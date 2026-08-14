from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from tools.pinned_workspace import MANIFEST, WorkspaceError, _authenticated, _redacted, materialize


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


if __name__ == "__main__":
    unittest.main()
