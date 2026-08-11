from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from tools.issue_router import route_feedback
from tools.improvement_loop import ImprovementLoopError, build_improvement_loop
from tools.validate import load_yaml, validate_improvement_loop


ROOT = Path(__file__).resolve().parents[1]


def feedback(name: str) -> dict:
    with (ROOT / "tests/fixtures/feedback" / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def manifest() -> dict:
    return load_yaml(ROOT / "config/repositories.yaml")


def execution() -> list[dict]:
    with (ROOT / "tests/fixtures/improvement/execution.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def routing(*signals: dict) -> dict:
    return route_feedback(list(signals), manifest(), "ISSUE-ROUTER-001:improvement-test")


class ImprovementLoopTests(unittest.TestCase):
    def test_passed_worker_evidence_reaches_human_gated_draft_plan(self):
        result = build_improvement_loop(
            routing(feedback("valid_explicit.json"), feedback("valid_inferred.json")),
            execution(),
            manifest(),
            "IMPROVEMENT-001:test-pass",
        )

        outcomes = {item["summary_code"]: item for item in result["outcomes"]}
        ready = outcomes["request:add-art-evidence"]
        triage = outcomes["friction:repeated-context-request"]
        self.assertEqual("DRAFT_PR_READY", ready["delivery_status"])
        self.assertEqual("PASSED", ready["quality_gate_status"])
        self.assertTrue(ready["draft_pr_plan"]["human_gate"])
        self.assertFalse(ready["draft_pr_plan"]["merge_permitted"])
        self.assertFalse(ready["draft_pr_plan"]["release_permitted"])
        self.assertEqual("TRIAGE", triage["delivery_status"])
        self.assertIsNone(triage["work_item"])
        self.assertEqual(1, len(result["draft_pr_plans"]))
        self.assertEqual([], result["remote_operations"])
        self.assertEqual([], validate_improvement_loop(result, manifest()))

    def test_eligible_issue_without_worker_evidence_is_checkpointed_and_waits(self):
        result = build_improvement_loop(
            routing(feedback("valid_explicit.json")),
            [],
            manifest(),
            "IMPROVEMENT-001:test-wait",
        )
        outcome = result["outcomes"][0]

        self.assertEqual("WAITING", outcome["delivery_status"])
        self.assertEqual("SELECTED", outcome["work_item"]["scheduler_status"])
        self.assertEqual("IN_PROGRESS", outcome["work_item"]["terminal_state"])
        self.assertEqual("NOT_STARTED", outcome["implementation_status"])
        self.assertEqual("NOT_STARTED", outcome["checkpoints"][1]["status"])
        self.assertIsNone(outcome["draft_pr_plan"])
        self.assertEqual([], result["draft_pr_plans"])

    def test_failed_quality_gate_blocks_without_draft_plan(self):
        evidence = execution()
        evidence[0]["quality_gate_status"] = "FAILED"
        result = build_improvement_loop(
            routing(feedback("valid_explicit.json")),
            evidence,
            manifest(),
            "IMPROVEMENT-001:test-failed-gate",
        )
        outcome = result["outcomes"][0]

        self.assertEqual("BLOCKED", outcome["delivery_status"])
        self.assertEqual("FAILED", outcome["quality_gate_status"])
        self.assertEqual("FAILED", outcome["checkpoints"][3]["status"])
        self.assertIsNone(outcome["draft_pr_plan"])
        self.assertEqual([], result["draft_pr_plans"])

    def test_duplicate_issue_key_is_suppressed_before_worker_execution(self):
        first = feedback("valid_explicit.json")
        second = copy.deepcopy(first)
        second["feedback_id"] = "feedback:interaction-001:003"
        routed = routing(first, second)
        result = build_improvement_loop(routed, execution(), manifest(), "IMPROVEMENT-001:test-duplicate")

        self.assertEqual(1, len(result["outcomes"]))
        self.assertEqual(1, len(result["duplicate_suppressions"]))
        self.assertEqual(1, len(result["draft_pr_plans"]))
        self.assertEqual(
            sorted([first["feedback_id"], second["feedback_id"]]),
            result["outcomes"][0]["source_feedback_ids"],
        )

    def test_commit_or_write_scope_mismatch_is_rejected(self):
        evidence = execution()
        evidence[0]["base_commit"] = "0" * 40
        with self.assertRaisesRegex(ImprovementLoopError, "different base commit"):
            build_improvement_loop(routing(feedback("valid_explicit.json")), evidence, manifest())

        evidence = execution()
        evidence[0]["changed_paths"] = ["tools/unsafe.py"]
        with self.assertRaisesRegex(ImprovementLoopError, "out-of-scope path"):
            build_improvement_loop(routing(feedback("valid_explicit.json")), evidence, manifest())

    def test_inputs_are_immutable_and_result_is_deterministic(self):
        routed = routing(feedback("valid_explicit.json"), feedback("valid_inferred.json"))
        evidence = execution()
        before_routing = copy.deepcopy(routed)
        before_evidence = copy.deepcopy(evidence)
        first = build_improvement_loop(routed, evidence, manifest(), "IMPROVEMENT-001:deterministic")
        second = build_improvement_loop(routed, evidence, manifest(), "IMPROVEMENT-001:deterministic")

        self.assertEqual(first, second)
        self.assertEqual(before_routing, routed)
        self.assertEqual(before_evidence, evidence)
        self.assertNotIn("conversation", json.dumps(first))

    def test_raw_execution_metadata_and_remote_operation_are_rejected(self):
        evidence = execution()
        evidence[0]["message"] = "raw worker output"
        with self.assertRaisesRegex(ImprovementLoopError, "forbidden raw"):
            build_improvement_loop(routing(feedback("valid_explicit.json")), evidence, manifest())

        result = build_improvement_loop(routing(feedback("valid_explicit.json")), execution(), manifest())
        result["remote_operations"] = [{"operation": "CREATE_PR"}]
        errors = validate_improvement_loop(result, manifest())
        self.assertTrue(any("remote operations" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
