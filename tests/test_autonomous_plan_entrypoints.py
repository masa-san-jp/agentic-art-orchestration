from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.run import BlockedPrecondition, _resume_command, _run_orchestration


class AutonomousPlanEntrypointTests(unittest.TestCase):
    def test_theme_free_normal_entry_derives_a_question_without_manual_fallback(self):
        with tempfile.TemporaryDirectory(prefix="autonomous-plan-entry-") as temporary:
            state_root = Path(temporary) / "state"
            report = _run_orchestration(
                None,
                Path(temporary) / "workspace",
                state_root,
                "AUTO-ENTRY-001",
                "artistic-research",
                None,
                None,
                "2026-09-12T00:00:00+00:00",
                sys.executable,
                limit=1,
                offline_fixture=True,
            )
            self.assertEqual("AT_EDGE", report["status"])
            self.assertEqual("REPOSITORY_DERIVED", report["theme_proposal"]["mode"])
            self.assertEqual("internal", report["delivery_contract"]["target"])
            self.assertEqual("INCOMPLETE", report["delivery_completion"]["status"])
            self.assertIn("FORBIDDEN", report["next_action"]["manual_fallback"])
            saved = json.loads((state_root / "AUTO-ENTRY-001" / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(report["delivery_contract"], saved["delivery_contract"])

    def test_project_root_resume_uses_project_root_without_conflicting_state_root(self):
        command = _resume_command(
            python="python3",
            run_id="AUTO-ENTRY-002",
            workspace_root=Path("/tmp/pinned-workspace"),
            state_root=Path("/tmp/state"),
            research_root=None,
            production_root=None,
            research_work_root=None,
            profile_root=None,
            purpose="artistic-research",
            intent=None,
            slug=None,
            title=None,
            offline_fixture=False,
            project_root=Path("/tmp/project"),
        )
        self.assertIn("--project-root", command)
        self.assertNotIn("--state-root", command)

    def test_project_local_run_resume_preserves_the_selected_destination(self):
        with tempfile.TemporaryDirectory(prefix="autonomous-plan-project-resume-") as temporary:
            root = Path(temporary)
            resolution = {
                "contract_version": "destination-resolution/v2",
                "project_root": str(root / "project"),
                "destinations": {},
            }
            with patch("tools.run._prepare_runtime_workspace", side_effect=BlockedPrecondition("pin drift")):
                with self.assertRaises(BlockedPrecondition):
                    _run_orchestration(
                        None,
                        root / "workspace",
                        root / "state",
                        "AUTO-ENTRY-004",
                        "artistic-research",
                        None,
                        None,
                        "2026-09-12T00:00:00+00:00",
                        sys.executable,
                        destination_resolution=resolution,
                    )
            saved = json.loads((root / "state" / "AUTO-ENTRY-004" / "run.json").read_text(encoding="utf-8"))
            self.assertIn("--project-root", saved["next_action"]["resume_command"])
            self.assertNotIn("--state-root", saved["next_action"]["resume_command"])

    def test_startup_block_is_persisted_with_an_agent_resume_action(self):
        with tempfile.TemporaryDirectory(prefix="autonomous-plan-blocked-") as temporary:
            state_root = Path(temporary) / "state"
            with patch("tools.run._prepare_runtime_workspace", side_effect=BlockedPrecondition("pin drift")):
                with self.assertRaises(BlockedPrecondition):
                    _run_orchestration(
                        None,
                        Path(temporary) / "workspace",
                        state_root,
                        "AUTO-ENTRY-003",
                        "artistic-research",
                        None,
                        None,
                        "2026-09-12T00:00:00+00:00",
                        sys.executable,
                    )
            saved = json.loads((state_root / "AUTO-ENTRY-003" / "run.json").read_text(encoding="utf-8"))
            self.assertEqual("BLOCKED", saved["status"])
            self.assertEqual("INCOMPLETE", saved["delivery_completion"]["status"])
            self.assertEqual("agent", saved["next_action"]["actor"])
            self.assertIn("--state-root", saved["next_action"]["resume_command"])


if __name__ == "__main__":
    unittest.main()
