from __future__ import annotations

import copy
import unittest

from tools.scheduler import schedule


def work_item(
    item_id: str,
    state: str = "READY",
    paths: list[str] | None = None,
    depends_on: list[str] | None = None,
    lease_status: str = "available",
    lease_owner: str = "unassigned",
) -> dict:
    return {
        "version": 1,
        "id": item_id,
        "title": item_id,
        "owner_repository": "agentic-art-orchestration",
        "target_repositories": ["agentic-art-orchestration"],
        "allowed_paths": paths or [f"tools/{item_id.lower()}.py"],
        "depends_on": depends_on or [],
        "context": {"required_files": ["AGENTS.md"], "contracts": [], "source_commits": {}},
        "acceptance": [{"id": "done", "description": "done", "observable": "test"}],
        "checks": [{"repository": "agentic-art-orchestration", "command": "python3 -m unittest", "required": True}],
        "risk": {"level": "low", "data_boundary": "no-sensitive", "mitigations": ["metadata only"]},
        "attempts": {"used": 0, "max": 3},
        "lease": {"status": lease_status, "owner": lease_owner, "expires_at": "2026-08-11T17:30:00+09:00"},
        "checkpoint": {"start_point": "e8f7fdf", "next_action": "test", "last_result": "not_started"},
        "terminal_criteria": ["test passes"],
        "terminal_state": state,
        "evidence": {"commits": [], "pull_requests": [], "tests": [], "changed_paths": []},
    }


class SchedulerTests(unittest.TestCase):
    def test_selects_ready_done_dependencies_and_explains_conflicts(self):
        items = [
            work_item("WORKITEM-001", state="DONE"),
            work_item("SCHEDULER-001", depends_on=["WORKITEM-001"], paths=["tools/scheduler.py"]),
            work_item("SCHEDULER-002", depends_on=["WORKITEM-001"], paths=["tools/scheduler.py" ]),
            work_item("SCHEDULER-003", depends_on=["WORKITEM-001"], paths=["tools/runtime.py"]),
            work_item("SCHEDULER-004", depends_on=["WORKITEM-001"], paths=["tools/other.py"]),
            work_item("WAIT-001", depends_on=["BLOCKED-001"], paths=["tools/wait.py"]),
            work_item("BLOCKED-001", state="BLOCKED", paths=["tools/blocked.py"]),
            work_item("ACTIVE-001", state="IN_PROGRESS", paths=["tools/runtime.py"], lease_status="held", lease_owner="worker-a"),
        ]
        result = schedule(items)

        self.assertEqual(["SCHEDULER-001", "SCHEDULER-004"], result["selected"])
        excluded = {entry["id"]: entry["reasons"] for entry in result["excluded"]}
        self.assertIn("allowed path conflict with selected 'SCHEDULER-001'", excluded["SCHEDULER-002"])
        self.assertIn("allowed path conflict with active 'ACTIVE-001'", excluded["SCHEDULER-003"])
        self.assertIn("dependency 'BLOCKED-001' is 'BLOCKED', not DONE", excluded["WAIT-001"])
        self.assertIn("terminal_state is 'DONE', not READY", excluded["WORKITEM-001"])

    def test_scheduler_is_deterministic_and_does_not_mutate_items(self):
        items = [work_item("SCHEDULER-002"), work_item("SCHEDULER-001")]
        before = copy.deepcopy(items)
        first = schedule(items)
        second = schedule(items)
        self.assertEqual(before, items)
        self.assertEqual(first, second)
        self.assertEqual(["SCHEDULER-001", "SCHEDULER-002"], first["selected"])

    def test_limit_explains_eligible_items_not_selected(self):
        result = schedule([work_item("SCHEDULER-001"), work_item("SCHEDULER-002")], limit=1)
        self.assertEqual(["SCHEDULER-001"], result["selected"])
        excluded = next(entry for entry in result["excluded"] if entry["id"] == "SCHEDULER-002")
        self.assertEqual(["selection limit 1 reached"], excluded["reasons"])

    def test_invalid_item_is_excluded_with_first_remediation(self):
        invalid = work_item("SCHEDULER-001")
        invalid["checks"][0]["command"] = "python3 check.py; rm -rf output"
        result = schedule([invalid])
        self.assertEqual([], result["selected"])
        self.assertIn("invalid work item:", result["excluded"][0]["reasons"][0])
        self.assertIn("remediation:", result["excluded"][0]["reasons"][0])


if __name__ == "__main__":
    unittest.main()
