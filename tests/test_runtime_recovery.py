from __future__ import annotations

import copy
import unittest
from pathlib import Path

import yaml

from tools.runtime import (
    RuntimeTransitionError,
    acquire_lease,
    complete_work_item,
    expire_lease,
    record_evidence,
    release_lease,
    retry_or_block,
    save_checkpoint,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/work-items/valid.yaml"


def load_state() -> dict:
    with FIXTURE.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class RuntimeRecoveryTests(unittest.TestCase):
    def test_acquire_checkpoint_release_and_reacquire(self):
        state = load_state()
        active = acquire_lease(state, "worker-a", "2026-08-11T16:00:00+09:00")
        self.assertEqual("IN_PROGRESS", active["terminal_state"])
        self.assertEqual("held", active["lease"]["status"])
        self.assertEqual(1, active["attempts"]["used"])
        checkpointed = save_checkpoint(active, "worker-a", "run declared checks", decision="keep source commit")
        released = release_lease(checkpointed, "worker-a")
        resumed = acquire_lease(released, "worker-b", "2026-08-11T16:10:00+09:00")
        self.assertEqual(active["checkpoint"]["execution_id"], resumed["checkpoint"]["execution_id"])
        self.assertEqual(1, resumed["attempts"]["used"])
        self.assertEqual("keep source commit", resumed["checkpoint"]["decision"])

    def test_kill_resume_does_not_duplicate_commit_pr_or_decision(self):
        state = acquire_lease(load_state(), "worker-a", "2026-08-11T16:00:00+09:00", lease_minutes=5)
        state = save_checkpoint(state, "worker-a", "wait for child checks", decision="preserve evidence")
        state = record_evidence(
            state,
            commits=["a" * 40],
            pull_requests=["https://github.com/example/project/pull/1"],
            tests=["python3 -m unittest"],
        )
        expired = expire_lease(state, "2026-08-11T16:05:00+09:00")
        resumed = acquire_lease(expired, "worker-b", "2026-08-11T16:06:00+09:00", lease_minutes=5)
        resumed = record_evidence(
            resumed,
            commits=["a" * 40],
            pull_requests=["https://github.com/example/project/pull/1"],
            tests=["python3 -m unittest"],
        )
        resumed = save_checkpoint(resumed, "worker-b", "none", result="passed", decision="preserve evidence")
        done = complete_work_item(resumed, "worker-b")
        done_again = complete_work_item(done, "worker-b")

        self.assertEqual("DONE", done["terminal_state"])
        self.assertEqual(1, len(done["evidence"]["commits"]))
        self.assertEqual(1, len(done["evidence"]["pull_requests"]))
        self.assertEqual(1, len(done["evidence"]["tests"]))
        self.assertEqual("preserve evidence", done["checkpoint"]["decision"])
        self.assertEqual(done, done_again)

    def test_retry_budget_transitions_to_blocked(self):
        state = load_state()
        state["attempts"]["max"] = 2
        state = acquire_lease(state, "worker-a", "2026-08-11T16:00:00+09:00")
        state = retry_or_block(state, "worker-a", "repair test failure")
        self.assertEqual("READY", state["terminal_state"])
        state = acquire_lease(state, "worker-b", "2026-08-11T16:10:00+09:00")
        state = retry_or_block(state, "worker-b", "same test failure")
        self.assertEqual("BLOCKED", state["terminal_state"])
        self.assertEqual("blocked", state["checkpoint"]["last_result"])

    def test_active_lease_and_unexpired_lease_are_protected(self):
        state = acquire_lease(load_state(), "worker-a", "2026-08-11T16:00:00+09:00")
        with self.assertRaisesRegex(RuntimeTransitionError, "already held.*remediation"):
            acquire_lease(state, "worker-b", "2026-08-11T16:01:00+09:00")
        with self.assertRaisesRegex(RuntimeTransitionError, "has not expired.*remediation"):
            expire_lease(state, "2026-08-11T16:01:00+09:00")

    def test_transition_does_not_mutate_input(self):
        state = load_state()
        before = copy.deepcopy(state)
        acquire_lease(state, "worker-a", "2026-08-11T16:00:00+09:00")
        self.assertEqual(before, state)


if __name__ == "__main__":
    unittest.main()
