from __future__ import annotations

import copy
import unittest
from pathlib import Path

import yaml

from tools.dispatcher import DispatchError, build_context_pack, load_context_files


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/work-items/valid.yaml"


def load_work_item() -> dict:
    with FIXTURE.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class DispatcherTests(unittest.TestCase):
    def test_pack_contains_only_required_files_and_recovery_context(self):
        item = load_work_item()
        contents = {
            "AGENTS.md": "worker rules",
            "execution/task-queue.yaml": "queue",
            "execution/state.yaml": "state",
            "docs/20260811-agentic-art-orchestration-system-design-specification.md": "contract context",
            "unrequested.txt": "must not be dispatched",
        }
        recovery = {
            "terminal_state": "IN_PROGRESS",
            "attempts": {"used": 1, "max": 3},
            "lease": {"status": "held", "owner": "worker-a", "expires_at": "2026-08-11T17:00:00+09:00", "execution_id": "WORKITEM-001:attempt-1"},
            "checkpoint": {"start_point": "e8f7fdf", "next_action": "run checks", "last_result": "checkpointed", "decision": "preserve source commit", "execution_id": "WORKITEM-001:attempt-1"},
            "evidence": {"commits": [], "pull_requests": [], "tests": ["previous check"], "changed_paths": ["tools/validate.py"]},
        }

        pack = build_context_pack(item, contents, ["keep source commits", "respect allowed paths"], recovery)

        self.assertEqual(["AGENTS.md", "docs/20260811-agentic-art-orchestration-system-design-specification.md", "execution/state.yaml", "execution/task-queue.yaml"], [entry["path"] for entry in pack["files"]])
        self.assertNotIn("unrequested.txt", {entry["path"] for entry in pack["files"]})
        self.assertEqual("IN_PROGRESS", pack["recovery"]["terminal_state"])
        self.assertEqual("preserve source commit", pack["recovery"]["checkpoint"]["decision"])
        self.assertEqual(["keep source commits", "respect allowed paths"], pack["rules"])
        self.assertEqual(sorted(item["allowed_paths"]), pack["task"]["allowed_paths"])

    def test_pack_is_deterministic_and_does_not_mutate_inputs(self):
        item = load_work_item()
        before = copy.deepcopy(item)
        contents = {path: path for path in item["context"]["required_files"]}
        first = build_context_pack(item, contents, ["b rule", "a rule"])
        second = build_context_pack(item, contents, ["a rule", "b rule"])

        self.assertEqual(first, second)
        self.assertEqual(before, item)

    def test_sensitive_content_and_unsafe_paths_are_rejected(self):
        item = load_work_item()
        contents = {path: "safe" for path in item["context"]["required_files"]}
        contents["AGENTS.md"] = "password: do-not-dispatch"
        with self.assertRaisesRegex(DispatchError, "sensitive assignment.*remediation"):
            build_context_pack(item, contents)

        unsafe = copy.deepcopy(item)
        unsafe["context"]["required_files"] = ["../secret.txt"]
        with self.assertRaisesRegex(DispatchError, "unsafe.*remediation"):
            build_context_pack(unsafe, {"../secret.txt": "safe"})

    def test_loader_rejects_context_root_escape_and_missing_file(self):
        item = load_work_item()
        with self.assertRaisesRegex(DispatchError, "missing.*remediation"):
            load_context_files(item, ROOT / "tests")


if __name__ == "__main__":
    unittest.main()
