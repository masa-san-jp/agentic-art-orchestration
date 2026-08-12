from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_TOOL = ROOT / "tools/workspace.py"
SPEC = importlib.util.spec_from_file_location("workspace_tool", WORKSPACE_TOOL)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def run_workspace(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WORKSPACE_TOOL), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class WorkspaceInitTests(unittest.TestCase):
    def test_offline_workspace_onboards_an_additional_repository_idempotently(self):
        manifest = copy.deepcopy(MODULE.load_manifest())
        added = copy.deepcopy(manifest["repositories"][0])
        added.update(
            {
                "id": "additional-knowledge",
                "full_name": "masa-san-jp/additional-knowledge-notes",
                "url": "https://github.com/masa-san-jp/additional-knowledge-notes.git",
                "path": "additional-knowledge-notes",
                "authority": "additional synthetic knowledge and evidence",
                "observed_commit": "a" * 40,
                "requirement_ssot": "https://github.com/masa-san-jp/additional-knowledge-notes/issues/1",
            }
        )
        manifest["repositories"].append(added)

        with tempfile.TemporaryDirectory(prefix="workspace-addition-test-") as temporary:
            root = Path(temporary)
            workspace = root / "repos"
            fixture = root / "fixture"
            first = MODULE.init_workspace(manifest, workspace, True, fixture)
            second = MODULE.init_workspace(manifest, workspace, True, fixture)
            status = MODULE.status_workspace(manifest, workspace)
            self.assertEqual(6, first["changed_count"])
            self.assertEqual(0, second["changed_count"])
            self.assertEqual(6, len(status["repositories"]))
            self.assertTrue(all(repo["state"] == "clean" for repo in status["repositories"]))

    def test_offline_init_is_idempotent_and_status_is_clean(self):
        with tempfile.TemporaryDirectory(prefix="workspace-test-") as temporary:
            root = Path(temporary)
            workspace = root / "repos"
            fixture = root / "fixture"
            first = run_workspace(
                "init",
                "--offline-fixture",
                "--workspace-root",
                str(workspace),
                "--fixture-root",
                str(fixture),
            )
            self.assertEqual(0, first.returncode, first.stderr)
            first_payload = json.loads(first.stdout)
            self.assertEqual(5, first_payload["changed_count"])
            self.assertTrue(first_payload["fixture_created"])
            self.assertEqual({"cloned"}, {repo["action"] for repo in first_payload["repositories"]})

            second = run_workspace(
                "init",
                "--offline-fixture",
                "--workspace-root",
                str(workspace),
                "--fixture-root",
                str(fixture),
            )
            self.assertEqual(0, second.returncode, second.stderr)
            second_payload = json.loads(second.stdout)
            self.assertEqual(0, second_payload["changed_count"])
            self.assertFalse(second_payload["fixture_created"])
            self.assertEqual({"unchanged"}, {repo["action"] for repo in second_payload["repositories"]})
            self.assertEqual(
                [repo["head"] for repo in first_payload["repositories"]],
                [repo["head"] for repo in second_payload["repositories"]],
            )

            status = run_workspace("status", "--json", "--workspace-root", str(workspace))
            self.assertEqual(0, status.returncode, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertEqual(5, len(status_payload["repositories"]))
            self.assertTrue(all(repo["exists"] for repo in status_payload["repositories"]))
            self.assertTrue(all(repo["state"] == "clean" for repo in status_payload["repositories"]))
            self.assertTrue(all(repo["branch"] == "main" for repo in status_payload["repositories"]))
            self.assertTrue(all(not repo["dirty"] for repo in status_payload["repositories"]))

    def test_offline_fetch_does_not_checkout_or_change_stable_refs(self):
        with tempfile.TemporaryDirectory(prefix="workspace-fetch-test-") as temporary:
            root = Path(temporary)
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
            fetched = run_workspace(
                "fetch",
                "--offline-fixture",
                "--workspace-root",
                str(workspace),
                "--fixture-root",
                str(fixture),
            )
            self.assertEqual(0, fetched.returncode, fetched.stderr)
            payload = json.loads(fetched.stdout)
            self.assertEqual(0, payload["changed_count"])
            self.assertEqual(5, len(payload["repositories"]))


if __name__ == "__main__":
    unittest.main()
