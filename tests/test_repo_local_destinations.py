import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.repo_local_destinations import RepoLocalDestinationError, resolve_project_root, write_resolution_evidence


class RepoLocalDestinationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(os.environ.get("AAK_PROJECT_SOURCE", "/private/tmp/aa217-project"))
        if not (cls.source / ".git").exists():
            raise unittest.SkipTest("qualified Project checkout is unavailable")

    def clone(self, parent: Path, name: str) -> Path:
        destination = parent / name
        subprocess.run(["git", "clone", "-q", str(self.source), str(destination)], check=True)
        return destination

    def test_two_clone_paths_have_the_same_fixed_relative_layout(self):
        with tempfile.TemporaryDirectory(prefix="repo-local-v2-") as directory:
            root = Path(directory)
            first, second = self.clone(root, "first"), self.clone(root, "second")
            left = resolve_project_root(first, run_id="RUN001", project_id="project/one")
            right = resolve_project_root(second, run_id="RUN001", project_id="project/one")
            self.assertEqual(
                {key: item["relative"] for key, item in left["destinations"].items()},
                {key: item["relative"] for key, item in right["destinations"].items()},
            )
            self.assertNotEqual(left["project_root"], right["project_root"])
            self.assertEqual("destination-resolution/v2", left["contract_version"])

    def test_environment_and_cli_are_mutually_exclusive_and_no_write_preflight(self):
        with tempfile.TemporaryDirectory(prefix="repo-local-v2-") as directory:
            project = self.clone(Path(directory), "project")
            with self.assertRaisesRegex(RepoLocalDestinationError, "AMBIGUOUS_DESTINATION_MODE"):
                resolve_project_root(project, environment={"AGENTIC_ART_PROJECT_ROOT": str(project)})
            self.assertFalse((project / ".agentic-art").exists())

    def test_resolution_evidence_is_create_only_and_private(self):
        with tempfile.TemporaryDirectory(prefix="repo-local-v2-") as directory:
            project = self.clone(Path(directory), "project")
            resolution = resolve_project_root(project, run_id="RUN001")
            path = write_resolution_evidence(project, "RUN001", resolution)
            self.assertEqual(path, project / ".agentic-art/state/RUN001/destination-resolution.json")
            before = path.read_bytes()
            self.assertEqual(path, write_resolution_evidence(project, "RUN001", resolution))
            self.assertEqual(before, path.read_bytes())
            changed = dict(resolution)
            changed["project_id"] = "other"
            with self.assertRaisesRegex(RepoLocalDestinationError, "RESOLUTION_CONFLICT"):
                write_resolution_evidence(project, "RUN001", changed)

    def test_forced_tracking_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="repo-local-v2-") as directory:
            project = self.clone(Path(directory), "project")
            private = project / ".agentic-art"
            private.mkdir()
            (private / "tracked.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "-f", ".agentic-art/tracked.txt"], cwd=project, check=True)
            with self.assertRaisesRegex(RepoLocalDestinationError, "PRIVATE_PATH_TRACKED|PROJECT_LAYOUT_INCOMPATIBLE"):
                resolve_project_root(project)


if __name__ == "__main__":
    unittest.main()
