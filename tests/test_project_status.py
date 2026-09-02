from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

import yaml

from tools.project_status import (
    ProjectStatusError,
    build_project_status,
    check_readme,
    render_json,
    render_markdown,
    replace_readme_marker,
    update_readme,
    validate_project_status,
)


def queue() -> dict:
    return {
        "updated_at": "2026-08-25T19:11:03+09:00",
        "tasks": [
            {"id": "DONE-001", "status": "DONE", "depends_on": []},
            {"id": "READY-002", "status": "READY", "depends_on": ["DONE-001"]},
            {
                "id": "BLOCKED-003",
                "status": "BLOCKED",
                "depends_on": [],
                "blocker": "human review is required",
            },
            {"id": "BACKLOG-004", "status": "BACKLOG", "depends_on": ["READY-002"]},
        ],
    }


def state() -> dict:
    return {
        "updated_at": "2026-08-25T19:11:03+09:00",
        "active_task": "READY-002",
        "active_repository": "agentic-art-orchestration",
        "checkpoint": {"task": "READY-002", "start_point": "abc123"},
        "resume_from": {"task": "READY-002", "action": "run the task"},
        "last_completed_task": "DONE-001",
    }


def hashes() -> dict[str, str]:
    return {"queue": "a" * 64, "state": "b" * 64}


class ProjectStatusTests(unittest.TestCase):
    def test_valid_report_has_contract_counts_current_ready_blocked_and_next(self):
        report = build_project_status(queue(), state(), hashes())

        self.assertEqual("project-status/v1", report["contract_version"])
        self.assertEqual({"BACKLOG": 1, "READY": 1, "IN_PROGRESS": 0, "BLOCKED": 1, "DONE": 1, "total": 4}, report["counts"])
        self.assertEqual("READY-002", report["current"]["task_id"])
        self.assertEqual(["READY-002"], report["ready"])
        self.assertEqual([{"task_id": "BLOCKED-003", "reason": "human review is required"}], report["blocked"])
        self.assertEqual("READY-002", report["next_task"])
        self.assertEqual([], validate_project_status(report, queue(), state()))

    def test_json_and_markdown_are_byte_identical_for_repeated_input(self):
        report = build_project_status(queue(), state(), hashes())

        self.assertEqual(render_json(report), render_json(copy.deepcopy(report)))
        self.assertEqual(render_markdown(report), render_markdown(copy.deepcopy(report)))

    def test_next_task_falls_back_to_lowest_eligible_backlog_when_ready_is_empty(self):
        source_queue = queue()
        source_queue["tasks"][1]["status"] = "BACKLOG"
        source_queue["tasks"][1]["depends_on"] = []
        report = build_project_status(source_queue, state(), hashes())

        self.assertEqual([], report["ready"])
        self.assertEqual("READY-002", report["next_task"])

    def test_schema_accepts_valid_report_and_rejects_missing_contract_field(self):
        report = build_project_status(queue(), state(), hashes())
        self.assertEqual([], validate_project_status(report, queue(), state()))

        invalid = copy.deepcopy(report)
        del invalid["contract_version"]
        self.assertTrue(any("contract_version" in error for error in validate_project_status(invalid, queue(), state())))

    def test_readme_marker_replacement_preserves_outside_text_and_detects_stale_content(self):
        report = build_project_status(queue(), state(), hashes())
        original = "prefix\n<!-- project-status:start -->\nold\n<!-- project-status:end -->\nsuffix\n"
        updated = replace_readme_marker(original, report)

        self.assertTrue(updated.startswith("prefix\n"))
        self.assertTrue(updated.endswith("suffix\n"))
        self.assertNotIn("\nold\n", updated)
        self.assertNotEqual(original, updated)
        self.assertEqual(updated, replace_readme_marker(updated, report))

    def test_readme_update_and_check_use_the_same_queue_state_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue_path = root / "queue.yaml"
            state_path = root / "state.yaml"
            readme_path = root / "README.md"
            queue_path.write_text(yaml.safe_dump(queue(), sort_keys=False), encoding="utf-8")
            state_path.write_text(yaml.safe_dump(state(), sort_keys=False), encoding="utf-8")
            readme_path.write_text("before\n<!-- project-status:start -->\nplaceholder\n<!-- project-status:end -->\nafter\n", encoding="utf-8")

            self.assertTrue(update_readme(readme_path, queue_path, state_path))
            self.assertTrue(check_readme(readme_path, queue_path, state_path))
            readme_path.write_text(readme_path.read_text(encoding="utf-8").replace("READY-002", "STALE"), encoding="utf-8")
            self.assertFalse(check_readme(readme_path, queue_path, state_path))

    def test_unknown_reference_done_current_ready_dependency_duplicate_and_counts_mismatch_fail(self):
        unknown = copy.deepcopy(queue())
        unknown["tasks"][1]["depends_on"] = ["MISSING"]
        with self.assertRaises(ProjectStatusError):
            build_project_status(unknown, state(), hashes())

        done_current = state()
        done_current["active_task"] = "DONE-001"
        with self.assertRaises(ProjectStatusError):
            build_project_status(queue(), done_current, hashes())

        incomplete = copy.deepcopy(queue())
        incomplete["tasks"][1]["depends_on"] = ["BLOCKED-003"]
        with self.assertRaises(ProjectStatusError):
            build_project_status(incomplete, state(), hashes())

        duplicate = copy.deepcopy(queue())
        duplicate["tasks"].append(copy.deepcopy(duplicate["tasks"][0]))
        with self.assertRaises(ProjectStatusError):
            build_project_status(duplicate, state(), hashes())

        report = build_project_status(queue(), state(), hashes())
        report["counts"]["total"] += 1
        self.assertTrue(any("counts mismatch" in error for error in validate_project_status(report, queue(), state())))


if __name__ == "__main__":
    unittest.main()
