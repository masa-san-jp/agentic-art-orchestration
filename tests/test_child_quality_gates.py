from __future__ import annotations

import copy
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("child_quality_gates", ROOT / "tools/child_quality_gates.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def make_repo(root: Path, gate_body: str, second_commit: bool = False) -> tuple[dict, str, str | None]:
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "gate.py").write_text(gate_body, encoding="utf-8")
    git(root, "add", "gate.py")
    git(root, "commit", "-q", "-m", "initial")
    observed = git(root, "rev-parse", "HEAD")
    current = None
    if second_commit:
        (root / "marker.txt").write_text("later\n", encoding="utf-8")
        git(root, "add", "marker.txt")
        git(root, "commit", "-q", "-m", "later")
        current = git(root, "rev-parse", "HEAD")
    return {"id": "child-one", "path": "child-one", "observed_commit": observed, "quality_gates": ["python3 gate.py"]}, observed, current


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
