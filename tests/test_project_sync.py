from __future__ import annotations

import copy
import unittest

import yaml

from tools.project_sync import ProjectSyncError, apply_plan_to_metadata, build_sync_plan, local_projection


CONFIG = yaml.safe_load(
    """
version: 1
project_number: 4
status_map:
  BACKLOG: Backlog
  READY: Ready
  IN_PROGRESS: In Progress
  DONE: Done
  BLOCKED: Blocked
priority_by_milestone:
  M3: 40
default_target_repositories: [agentic-art-orchestration]
default_human_gate: false
"""
)
TASKS = [
    {"id": "SYNC-002", "title": "second", "milestone": "M3", "status": "BACKLOG"},
    {"id": "SYNC-001", "title": "first", "milestone": "M3", "status": "READY", "priority": 5, "target_repositories": ["agentic-art-orchestration"], "human_gate": True},
]
STATE = {"active_task": "SYNC-001"}


class ProjectSyncTests(unittest.TestCase):
    def test_projection_maps_status_priority_targets_review_and_run(self):
        projection = local_projection(TASKS, STATE, CONFIG)
        first = next(item for item in projection if item["task_id"] == "SYNC-001")

        self.assertEqual("Ready", first["status"])
        self.assertEqual(5, first["priority"])
        self.assertEqual(["agentic-art-orchestration"], first["target_repositories"])
        self.assertTrue(first["human_gate"])
        self.assertEqual("SYNC-001", first["run_id"])

    def test_remote_plan_creates_updates_and_reports_orphans(self):
        remote = [
            {"task_id": "SYNC-001", "item_id": "PVT_1", "title": "old", "status": "Backlog", "priority": 5, "target_repositories": ["agentic-art-orchestration"], "human_gate": True, "run_id": None},
            {"task_id": "ORPHAN-001", "item_id": "PVT_2"},
        ]
        plan = build_sync_plan(TASKS, STATE, CONFIG, remote, api_available=True)
        actions = {operation["task_id"]: operation["action"] for operation in plan["operations"]}

        self.assertEqual("UPDATE", actions["SYNC-001"])
        self.assertEqual("CREATE", actions["SYNC-002"])
        self.assertEqual("ORPHAN-001", plan["orphan_remote_items"][0]["task_id"])
        self.assertEqual("MANUAL_REVIEW", plan["orphan_remote_items"][0]["action"])

    def test_same_remote_state_is_idempotent_after_metadata_apply(self):
        remote: list[dict] = []
        first = build_sync_plan(TASKS, STATE, CONFIG, remote, api_available=True)
        synchronized = apply_plan_to_metadata(remote, first)
        second = build_sync_plan(TASKS, STATE, CONFIG, synchronized, api_available=True)

        self.assertEqual([], [operation for operation in second["operations"] if operation["action"] != "UNCHANGED"])
        self.assertEqual(["UNCHANGED", "UNCHANGED"], [operation["action"] for operation in second["operations"]])

    def test_api_unavailable_keeps_local_execution_usable_without_operations(self):
        before = copy.deepcopy(TASKS)
        plan = build_sync_plan(TASKS, STATE, CONFIG, [{"task_id": "SYNC-001"}], api_available=False)

        self.assertEqual("LOCAL_ONLY", plan["mode"])
        self.assertEqual("CONTINUE", plan["local_execution"])
        self.assertEqual([], plan["operations"])
        self.assertIn("unavailable", plan["remote_error"])
        self.assertEqual(before, TASKS)

    def test_duplicate_remote_item_is_rejected_without_delete_fallback(self):
        remote = [{"task_id": "SYNC-001", "item_id": "PVT_1"}, {"task_id": "SYNC-001", "item_id": "PVT_2"}]
        with self.assertRaisesRegex(ProjectSyncError, "duplicate.*remediation"):
            build_sync_plan(TASKS, STATE, CONFIG, remote, api_available=True)


if __name__ == "__main__":
    unittest.main()
