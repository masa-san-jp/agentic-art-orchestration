from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("child_quality_gates", ROOT / "tools/child_quality_gates.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def make_repo(
    root: Path,
    gate_body: str,
    second_commit: bool = False,
    requirements: str | None = None,
) -> tuple[dict, str, str | None]:
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "gate.py").write_text(gate_body, encoding="utf-8")
    paths = ["gate.py"]
    if requirements is not None:
        (root / "requirements.txt").write_text(requirements, encoding="utf-8")
        paths.append("requirements.txt")
    git(root, "add", *paths)
    git(root, "commit", "-q", "-m", "initial")
    observed = git(root, "rev-parse", "HEAD")
    current = None
    if second_commit:
        (root / "marker.txt").write_text("later\n", encoding="utf-8")
        git(root, "add", "marker.txt")
        git(root, "commit", "-q", "-m", "later")
        current = git(root, "rev-parse", "HEAD")
    return {"id": "child-one", "path": "child-one", "observed_commit": observed, "quality_gates": ["python3 gate.py"]}, observed, current


def make_python_root(root: Path) -> tuple[Path, Path]:
    python_root = root / "child-environments"
    python_bin = python_root / "child-one" / "bin"
    python_bin.mkdir(parents=True)
    executable = python_bin / "python"
    executable.symlink_to(sys.executable)
    return python_root, executable


class ChildQualityGateTests(unittest.TestCase):
    def test_deterministic_view_ignores_runtime_duration_only(self):
        first = {"duration_ms": 10, "nested": [{"duration_ms": 20, "status": "PASSED"}]}
        second = {"duration_ms": 99, "nested": [{"duration_ms": 80, "status": "PASSED"}]}
        self.assertEqual(MODULE._deterministic_view(first), MODULE._deterministic_view(second))

    def test_runs_gates_from_observed_archive_and_does_not_change_stale_checkout(self):
        with tempfile.TemporaryDirectory(prefix="child-gates-") as temporary:
            workspace = Path(temporary)
            repository, observed, current = make_repo(workspace / "child-one", "print('observed')\n", second_commit=True)
            before = git(workspace / "child-one", "status", "--porcelain")
            manifest = {"version": 1, "repositories": [repository]}
            result = MODULE.run_child_quality_gates(manifest, workspace, run_id="fixture-run")
            record = result["results"][0]
            self.assertEqual("STALE", record["workspace_state"])
            self.assertEqual(current, record["workspace_commit"])
            self.assertEqual("PASSED", record["status"])
            self.assertEqual("immutable-archive", record["execution_mode"])
            self.assertIn("observed", record["gates"][0]["output_redacted"])
            self.assertEqual(before, git(workspace / "child-one", "status", "--porcelain"))
            self.assertEqual(current, git(workspace / "child-one", "rev-parse", "HEAD"))
            self.assertEqual(observed, repository["observed_commit"])

    def test_missing_observed_commit_is_blocked_without_running_gate(self):
        with tempfile.TemporaryDirectory(prefix="child-gates-missing-") as temporary:
            workspace = Path(temporary)
            repository, _observed, _current = make_repo(workspace / "child-one", "raise SystemExit(9)\n")
            repository["observed_commit"] = "a" * 40
            result = MODULE.run_child_quality_gates({"version": 1, "repositories": [repository]}, workspace)
            record = result["results"][0]
            self.assertEqual("BLOCKED", record["status"])
            self.assertEqual("NOT_RUN", record["execution_mode"])
            self.assertEqual("NOT_RUN", record["gates"][0]["status"])

    def test_failed_gate_is_preserved_and_output_is_redacted(self):
        with tempfile.TemporaryDirectory(prefix="child-gates-failed-") as temporary:
            workspace = Path(temporary)
            repository, _observed, _current = make_repo(workspace / "child-one", "print('password=secret-value')\nraise SystemExit(3)\n")
            result = MODULE.run_child_quality_gates({"version": 1, "repositories": [repository]}, workspace)
            record = result["results"][0]
            self.assertEqual("FAILED", record["status"])
            self.assertEqual("FAILED", record["gates"][0]["status"])
            self.assertNotIn("secret-value", record["gates"][0]["output_redacted"])
            self.assertIn("<REDACTED>", record["gates"][0]["output_redacted"])

    def test_missing_requirement_is_recorded_without_running_gate(self):
        with tempfile.TemporaryDirectory(prefix="child-gates-env-") as temporary:
            workspace = Path(temporary)
            repository, _observed, _current = make_repo(
                workspace / "child-one",
                "raise SystemExit(9)\n",
                requirements="fixture-missing-package>=1.0\n",
            )
            with patch.object(MODULE, "_installed_version", return_value=None):
                result = MODULE.run_child_quality_gates({"version": 1, "repositories": [repository]}, workspace)
            record = result["results"][0]
            self.assertEqual("ENV_UNSATISFIED", record["status"])
            self.assertEqual("NOT_RUN", record["execution_mode"])
            self.assertEqual("NOT_RUN", record["gates"][0]["status"])
            self.assertIn("fixture-missing-package", record["gates"][0]["error"])
            self.assertIn("pip install --user -r child-one/requirements.txt", record["remediation"])
            self.assertNotIn("SystemExit", record["gates"][0]["output_redacted"])

    def test_satisfied_requirement_preserves_gate_execution(self):
        with tempfile.TemporaryDirectory(prefix="child-gates-env-satisfied-") as temporary:
            workspace = Path(temporary)
            repository, _observed, _current = make_repo(
                workspace / "child-one",
                "print('satisfied')\n",
                requirements="fixture-installed-package>=1.0\n",
            )
            with patch.object(MODULE, "_installed_version", return_value="1.2"):
                result = MODULE.run_child_quality_gates({"version": 1, "repositories": [repository]}, workspace)
            record = result["results"][0]
            self.assertEqual("PASSED", record["status"])
            self.assertEqual("immutable-archive", record["execution_mode"])
            self.assertEqual("PASSED", record["gates"][0]["status"])
            self.assertIn("satisfied", record["gates"][0]["output_redacted"])

    def test_requirement_below_lower_bound_is_environment_unsatisfied(self):
        with tempfile.TemporaryDirectory(prefix="child-gates-env-old-") as temporary:
            workspace = Path(temporary)
            repository, _observed, _current = make_repo(
                workspace / "child-one",
                "raise SystemExit(9)\n",
                requirements="fixture-old-package>=2.0\n",
            )
            with patch.object(MODULE, "_installed_version", return_value="1.9"):
                result = MODULE.run_child_quality_gates({"version": 1, "repositories": [repository]}, workspace)
            record = result["results"][0]
            self.assertEqual("ENV_UNSATISFIED", record["status"])
            self.assertIn("below required >= 2.0", record["gates"][0]["error"])
            self.assertEqual("NOT_RUN", record["gates"][0]["status"])

    def test_satisfied_exact_requirement_preserves_gate_execution(self):
        with tempfile.TemporaryDirectory(prefix="child-gates-env-exact-satisfied-") as temporary:
            workspace = Path(temporary)
            repository, _observed, _current = make_repo(
                workspace / "child-one",
                "print('exact satisfied')\n",
                requirements="fixture-exact-package==1.2.0\n",
            )
            with patch.object(MODULE, "_installed_version", return_value="1.2"):
                result = MODULE.run_child_quality_gates({"version": 1, "repositories": [repository]}, workspace)
            record = result["results"][0]
            self.assertEqual("PASSED", record["status"])
            self.assertEqual("immutable-archive", record["execution_mode"])
            self.assertEqual("PASSED", record["gates"][0]["status"])
            self.assertIn("exact satisfied", record["gates"][0]["output_redacted"])

    def test_exact_requirement_mismatch_is_environment_unsatisfied_without_running_gate(self):
        with tempfile.TemporaryDirectory(prefix="child-gates-env-exact-mismatch-") as temporary:
            workspace = Path(temporary)
            repository, _observed, _current = make_repo(
                workspace / "child-one",
                "raise SystemExit(9)\n",
                requirements="fixture-exact-package==2.0.0\n",
            )
            with patch.object(MODULE, "_installed_version", return_value="1.9"):
                result = MODULE.run_child_quality_gates({"version": 1, "repositories": [repository]}, workspace)
            record = result["results"][0]
            self.assertEqual("ENV_UNSATISFIED", record["status"])
            self.assertEqual("NOT_RUN", record["execution_mode"])
            self.assertEqual("NOT_RUN", record["gates"][0]["status"])
            self.assertIn("does not equal required == 2.0.0", record["gates"][0]["error"])
            self.assertNotIn("SystemExit", record["gates"][0]["output_redacted"])

    def test_per_child_environment_is_used_for_preflight_and_gate(self):
        with tempfile.TemporaryDirectory(prefix="child-gates-per-child-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            repository, _observed, _current = make_repo(
                workspace / "child-one",
                "print('per-child')\n",
                requirements="fixture-exact-package==1.2.0\n",
            )
            python_root, python_executable = make_python_root(root)
            with patch.object(MODULE, "_installed_version_in_python", return_value="1.2") as installed:
                result = MODULE.run_child_quality_gates(
                    {"version": 1, "repositories": [repository]},
                    workspace,
                    python_root=python_root,
                )
            record = result["results"][0]
            self.assertEqual("per-child", record["environment_mode"])
            self.assertEqual("PASSED", record["status"])
            self.assertEqual("PASSED", record["gates"][0]["status"])
            installed.assert_called_once_with("fixture-exact-package", str(python_executable))

    def test_missing_per_child_environment_blocks_without_running_gate(self):
        with tempfile.TemporaryDirectory(prefix="child-gates-per-child-missing-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            repository, _observed, _current = make_repo(
                workspace / "child-one",
                "raise SystemExit(9)\n",
            )
            result = MODULE.run_child_quality_gates(
                {"version": 1, "repositories": [repository]},
                workspace,
                python_root=root / "missing-environments",
            )
            record = result["results"][0]
            self.assertEqual("per-child", record["environment_mode"])
            self.assertEqual("ENV_UNSATISFIED", record["status"])
            self.assertEqual("NOT_RUN", record["execution_mode"])
            self.assertEqual("NOT_RUN", record["gates"][0]["status"])
            self.assertIn("per-child Python environment is unavailable", record["gates"][0]["error"])

    def test_validator_rejects_unexpected_status_and_preserves_schema_remediation(self):
        with tempfile.TemporaryDirectory(prefix="child-gates-validator-") as temporary:
            workspace = Path(temporary)
            repository, _observed, _current = make_repo(workspace / "child-one", "print('ok')\n")
            result = MODULE.run_child_quality_gates({"version": 1, "repositories": [repository]}, workspace)
            invalid = copy.deepcopy(result)
            invalid["results"][0]["status"] = "BLOCKED"
            errors = MODULE.validate_child_quality_gates(invalid, "fixture:child-gates")
            rendered = "\n".join(errors)
            self.assertIn("BLOCKED", rendered)
            self.assertIn("remediation:", rendered)


if __name__ == "__main__":
    unittest.main()
