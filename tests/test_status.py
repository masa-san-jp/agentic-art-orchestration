from __future__ import annotations

import copy
import unittest

from tools.status import build_status, render_markdown


def snapshot() -> dict:
    return {
        "captured_at": "2026-08-11T06:47:52Z",
        "snapshot_hash": "a" * 64,
        "repositories": [
            {"id": "input-a", "head": "1" * 40, "branch": "main", "upstream": "origin/main", "dirty": False, "untracked": False, "detached": False, "ahead": 0, "behind": 0, "quality_gate_hash": "q" * 64, "manifest_observed_commit": "2" * 40, "contract": {"direction": "export", "version": "normalized-research-signal/v1"}},
            {"id": "consumer", "head": "3" * 40, "branch": "main", "upstream": "origin/main", "dirty": False, "untracked": False, "detached": False, "ahead": 0, "behind": 0, "quality_gate_hash": "r" * 64, "manifest_observed_commit": "4" * 40, "contract": {"direction": "import", "version": "normalized-research-signal/v1"}},
        ],
    }


def queue() -> dict:
    return {
        "updated_at": "2026-08-11T16:00:00+09:00",
        "tasks": [
            {"id": "STATUS-001", "status": "READY", "depends_on": ["DONE-001"]},
            {"id": "DONE-001", "status": "DONE", "depends_on": []},
            {"id": "BLOCKED-001", "status": "BLOCKED", "depends_on": []},
        ],
    }


def state() -> dict:
    return {"updated_at": "2026-08-11T16:01:00+09:00", "active_task": None, "blocked": []}


def live() -> list[dict]:
    return [
        {"id": "input-a", "head": "1" * 40, "branch": "main", "upstream": "origin/main", "dirty": False, "untracked": False, "detached": False, "ahead": 0, "behind": 0, "state": "clean"},
        {"id": "consumer", "head": "3" * 40, "branch": "main", "upstream": "origin/main", "dirty": False, "untracked": False, "detached": False, "ahead": 0, "behind": 0, "state": "clean"},
    ]


class StatusTests(unittest.TestCase):
    def test_report_contains_commits_progress_compatibility_blocker_and_next_work(self):
        report = build_status(snapshot(), queue(), state(), live(), "manifest")

        self.assertEqual("1" * 40, next(item for item in report["commits"] if item["repository"] == "input-a")["source_commit"])
        self.assertEqual("CLEAN", report["drift"]["status"])
        self.assertEqual(2, len(report["child_progress"]))
        self.assertEqual("COMPATIBLE", report["compatibility"]["status"])
        self.assertEqual("STATUS-001", report["next_work"]["task"])
        self.assertEqual("BLOCKED-001", report["blockers"][0]["id"])

    def test_drift_and_repository_guard_blocker_are_observable(self):
        changed = live()
        changed[0]["head"] = "9" * 40
        changed[0]["dirty"] = True
        report = build_status(snapshot(), queue(), state(), changed, "manifest")

        self.assertEqual("DRIFT", report["drift"]["status"])
        self.assertTrue(any(item["repository"] == "input-a" for item in report["drift"]["items"]))
        self.assertTrue(any(item["type"] == "repository" for item in report["blockers"]))

    def test_incompatible_contract_is_blocking(self):
        incompatible = snapshot()
        incompatible["repositories"][1]["contract"]["version"] = "normalized-research-signal/v2"
        report = build_status(incompatible, queue(), state(), live(), "manifest")

        self.assertEqual("INCOMPATIBLE", report["compatibility"]["status"])
        self.assertTrue(any(item["type"] == "compatibility" for item in report["blockers"]))

    def test_render_is_deterministic_and_inputs_are_not_mutated(self):
        source = [snapshot(), queue(), state(), live()]
        before = copy.deepcopy(source)
        first = build_status(*source, "manifest")
        second = build_status(*source, "manifest")

        self.assertEqual(first, second)
        self.assertEqual(render_markdown(first), render_markdown(second))
        self.assertEqual(before, source)


if __name__ == "__main__":
    unittest.main()
