from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from tools.run import (
    BlockedPrecondition,
    StepFailure,
    _guard_pinned_workspace,
    _project_identity,
    _run_orchestration,
    _theme_proposal,
)
import tools.run as run_module


class AutomaticPlanEntryTests(unittest.TestCase):
    def test_cli_orchestration_does_not_require_theme_or_project_naming(self) -> None:
        with patch("tools.run._run_orchestration", return_value={"status": "AT_EDGE"}) as orchestration:
            with contextlib.redirect_stdout(io.StringIO()):
                status = run_module.main([])

        self.assertEqual(0, status)
        call = orchestration.call_args.args
        self.assertIsNone(call[0])
        self.assertTrue(call[3].startswith("AUTO-PLAN-"))
        self.assertIsNone(call[5])
        self.assertIsNone(call[6])
        self.assertTrue(call[7])

    def test_project_identity_is_derived_from_run_id_when_naming_is_omitted(self) -> None:
        first = _project_identity("AUTO-PLAN:001")
        second = _project_identity("AUTO-PLAN:001")

        self.assertEqual(first, second)
        self.assertTrue(first[0].startswith("auto-auto-plan-001-"))
        self.assertEqual("Repository-derived production proposal", first[1])

    def test_theme_proposal_reads_the_candidate_derived_question(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-plan-request-") as directory:
            path = Path(directory) / "RR001.yaml"
            path.write_text(
                yaml.safe_dump(
                    {"intent": {"creative_question": "A candidate-derived question"}},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            proposal = _theme_proposal(path, explicit_intent=False)

        self.assertEqual("PROPOSED", proposal["status"])
        self.assertEqual("REPOSITORY_DERIVED", proposal["mode"])
        self.assertEqual("gate-passing-candidate", proposal["source"])
        self.assertEqual("A candidate-derived question", proposal["creative_question"])

    def test_invalid_request_cannot_be_presented_as_a_theme_proposal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-plan-invalid-") as directory:
            path = Path(directory) / "RR001.yaml"
            path.write_text("intent: {}\n", encoding="utf-8")

            with self.assertRaisesRegex(StepFailure, "no derived creative question"):
                _theme_proposal(path, explicit_intent=False)

    def test_orchestration_derives_theme_and_identity_without_user_input(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-plan-orchestration-") as directory:
            root = Path(directory)
            calls: list[list[str]] = []

            def fake_tool(args: list[str], python: str) -> dict:
                calls.append(args)
                if args[0].endswith("build_research_request.py"):
                    output = Path(args[args.index("--output") + 1])
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "RR001.yaml").write_text(
                        yaml.safe_dump(
                            {"intent": {"creative_question": "Derived from the passing candidate"}},
                            sort_keys=False,
                        ),
                        encoding="utf-8",
                    )
                return {"status": "PASSED"}

            with patch("tools.run._guard_pinned_workspace", return_value={"status": "PASSED"}), \
                    patch("tools.run._run_tool", side_effect=fake_tool):
                report = _run_orchestration(
                    None,
                    root / "workspace",
                    root / "state",
                    "AUTO-PLAN-001",
                    "artistic-research",
                    None,
                    None,
                    "2026-09-02T00:00:00+00:00",
                    "python3",
                )

        self.assertEqual("AT_EDGE", report["status"])
        self.assertEqual("REPOSITORY_DERIVED", report["theme_proposal"]["mode"])
        self.assertEqual("Derived from the passing candidate", report["theme_proposal"]["creative_question"])
        self.assertTrue(any(step["step"] == "workspace-preflight" for step in report["steps"]))
        request_call = next(args for args in calls if args[0].endswith("build_research_request.py"))
        self.assertIn("--slug", request_call)
        self.assertTrue(request_call[request_call.index("--slug") + 1].startswith("auto-auto-plan-001-"))
        self.assertIn("--title", request_call)

    def test_stale_workspace_is_blocked_before_child_export(self) -> None:
        with patch(
            "tools.workspace.load_manifest",
            return_value={"repositories": [{"id": "self-model", "observed_commit": "a" * 40}]},
        ), patch(
            "tools.workspace.guard_workspace",
            return_value={
                "repositories": [
                    {
                        "id": "self-model",
                        "blocked": False,
                        "observed": {"head": "b" * 40},
                        "reasons": [],
                    }
                ]
            },
        ):
            with self.assertRaisesRegex(BlockedPrecondition, "manifest pin mismatch"):
                _guard_pinned_workspace(Path("/tmp/auto-plan-stale-workspace"))

    def test_offline_cli_reaches_theme_proposal_without_any_theme_input(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-plan-offline-") as directory:
            state_root = Path(directory) / "state"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(run_module.ROOT / "tools/run.py"),
                    "--offline-fixture",
                    "--state-root",
                    str(state_root),
                    "--run-id",
                    "AUTO-PLAN-OFFLINE-TEST",
                    "--requested-at",
                    "2026-09-02T00:00:00+00:00",
                ],
                cwd=run_module.ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual("AT_EDGE", report["status"])
        self.assertEqual("REPOSITORY_DERIVED", report["theme_proposal"]["mode"])
        self.assertTrue(report["theme_proposal"]["creative_question"])
        self.assertIsNone(report["intent"])


if __name__ == "__main__":
    unittest.main()
