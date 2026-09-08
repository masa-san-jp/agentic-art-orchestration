from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.pinned_workspace import PINNED_WORKSPACE_MARKER, materialize_pinned_workspace
from tools import run as run_module


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


class ImmutableWorkspaceRecoveryTests(unittest.TestCase):
    def _repository(self, root: Path) -> tuple[dict, str]:
        root.mkdir(parents=True)
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "fixture@example.invalid")
        git(root, "config", "user.name", "Fixture")
        (root / "source.txt").write_text("qualified\n", encoding="utf-8")
        git(root, "add", "source.txt")
        git(root, "commit", "-q", "-m", "qualified")
        return {"id": "child", "path": "child", "observed_commit": git(root, "rev-parse", "HEAD")}, git(root, "rev-parse", "HEAD")

    def test_materialization_marks_exact_detached_workspace_and_run_accepts_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source_root = base / "sources"
            source, pin = self._repository(source_root / "child")
            destination = base / "pinned"
            manifest = {"repositories": [{**source, "quality_gates": []}]}
            materialize_pinned_workspace(manifest, source_root, destination)

            marker = json.loads((destination / PINNED_WORKSPACE_MARKER).read_text(encoding="utf-8"))
            self.assertEqual("manifest-pinned-workspace/v1", marker["contract_version"])
            self.assertEqual(pin, git(destination / "child", "rev-parse", "HEAD"))
            blocked_guard = {"repositories": [{"id": "child", "blocked": True, "reasons": [{"code": "detached", "detail": "detached", "remediation": "restore branch"}]}]}
            with patch("tools.workspace.load_manifest", return_value=manifest), patch("tools.workspace.guard_workspace", return_value=blocked_guard):
                report = run_module._guard_pinned_workspace(destination)
            self.assertEqual("MANIFEST_PINNED_IMMUTABLE", report["mode"])
            self.assertEqual("MATCHED", report["pin_status"])

    def test_unmarked_detached_checkout_is_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source, _ = self._repository(base / "source")
            checkout = base / "workspace" / "child"
            checkout.parent.mkdir()
            subprocess.run(["git", "clone", "-q", str(base / "source"), str(checkout)], check=True)
            git(checkout, "checkout", "-q", "--detach", "HEAD")
            manifest = {"repositories": [{**source, "quality_gates": []}]}
            with patch("tools.workspace.load_manifest", return_value=manifest), patch(
                "tools.workspace.guard_workspace",
                return_value={"repositories": [{"id": "child", "blocked": True, "reasons": [{"code": "detached", "detail": "detached", "remediation": "restore branch"}]}]},
            ):
                with self.assertRaises(run_module.BlockedPrecondition):
                    run_module._guard_pinned_workspace(base / "workspace")

    def test_recoverable_pin_block_uses_new_workspace_without_touching_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            recovered = Path(temporary) / "state" / "pinned-workspace"
            blocked = run_module.BlockedPrecondition("manifest pin mismatch")
            with patch.object(run_module, "_guard_pinned_workspace", side_effect=[blocked, {"status": "PASSED", "pin_status": "MATCHED"}]) as guard, \
                    patch.object(run_module, "_can_materialize_qualified_workspace", return_value=True), \
                    patch.object(run_module, "_materialize_qualified_workspace", return_value=recovered) as materialize:
                report, selected = run_module._prepare_runtime_workspace(source, Path(temporary) / "state")
            self.assertEqual("PASSED", report["status"])
            self.assertEqual(recovered, selected)
            materialize.assert_called_once_with(Path(temporary) / "state")
            self.assertEqual(2, guard.call_count)


class ResumeContractTests(unittest.TestCase):
    def test_manifest_resolves_runtime_roots_and_pending_report_has_exact_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("tools.workspace.load_manifest", return_value={"repositories": [
                {"id": "agentic-art-research", "path": "agentic-art-research"},
                {"id": "agentic-art-production", "path": "agentic-art-production"},
            ]}):
                research, production = run_module._manifest_runtime_roots(root / "workspace")
            self.assertEqual(root / "workspace" / "agentic-art-research", research)
            self.assertEqual(root / "workspace" / "agentic-art-production", production)
            command = run_module._resume_command(
                python="python3", run_id="RUN-001", workspace_root=root / "workspace",
                state_root=root / "state", research_root=research, production_root=production,
                research_work_root=root / "state" / "research-work", profile_root=root / "profile",
                purpose="artistic-research", intent=None, slug=None, title=None, offline_fixture=False,
            )
            report = run_module._at_research(
                root / "state" / "RUN-001", "RUN-001", None, [], research, "proposal",
                resume_command=command,
            )
            self.assertEqual("INCOMPLETE", report["completion_status"])
            self.assertEqual("NOT_READY", report["plan_status"])
            self.assertEqual("PENDING", report["knowledge_status"])
            self.assertEqual("NOT_RUN", report["projection_status"])
            self.assertEqual(command, report["next_action"]["resume_command"])
            self.assertIn("FORBIDDEN", report["next_action"]["manual_fallback"])

    def test_startup_block_persists_incomplete_report_and_resume_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            blocked = run_module.BlockedPrecondition(
                "qualified workspace BLOCKED: declared pins unavailable; remediation: retry"
            )
            with patch.object(run_module, "_prepare_runtime_workspace", side_effect=blocked):
                with self.assertRaises(run_module.BlockedPrecondition):
                    run_module._run_orchestration(
                        None, root / "workspace", state, "BLOCKED-RUN", "artistic-research",
                        None, None, "2026-09-09T00:00:00+00:00", "python3",
                        profile_root=root / "profile",
                    )
            report = json.loads((state / "BLOCKED-RUN" / "run.json").read_text(encoding="utf-8"))
            self.assertEqual("BLOCKED", report["status"])
            self.assertEqual("INCOMPLETE", report["completion_status"])
            self.assertEqual("NOT_READY", report["plan_status"])
            self.assertEqual("NOT_STARTED", report["knowledge_status"])
            self.assertEqual("NOT_RUN", report["projection_status"])
            self.assertEqual("BLOCKED", report["run_status"])
            self.assertEqual("BLOCKED-RUN", report["next_action"]["resume_command"][report["next_action"]["resume_command"].index("--run-id") + 1])
            self.assertIn("FORBIDDEN", report["next_action"]["manual_fallback"])


if __name__ == "__main__":
    unittest.main()
