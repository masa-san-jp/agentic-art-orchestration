from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from tools.async_auditor import AsyncAuditorError, build_async_audit
from tools.validate import validate_async_audit


ROOT = Path(__file__).resolve().parents[1]
SELF_COMMIT = "1" * 40
PARENT_COMMIT = "9" * 40
SNAPSHOT_HASH = "a" * 64


def snapshot() -> dict:
    return {
        "snapshot_hash": SNAPSHOT_HASH,
        "captured_at": "2026-08-11T20:51:00+09:00",
        "parent_commit": PARENT_COMMIT,
        "repositories": [
            {
                "id": "self-model",
                "head": SELF_COMMIT,
                "dirty": False,
                "detached": False,
                "ahead": 0,
                "behind": 0,
            }
        ],
    }


def lease(**overrides) -> dict:
    value = {
        "lane": "ASYNC_AUDIT",
        "status": "held",
        "owner": "auditor-worker",
        "execution_id": "AUDITOR-002:attempt-1",
        "expires_at": "2026-08-11T21:42:05+09:00",
    }
    value.update(overrides)
    return value


def audit(findings: list[dict] | None = None) -> dict:
    findings = findings or []
    return {
        "version": 1,
        "generated_at": "2026-08-11T20:51:00Z",
        "blocking": False,
        "status": "CLEAN" if not findings else "FINDINGS",
        "summary": {"finding_count": len(findings), "error_count": 0},
        "finding_count": len(findings),
        "findings": findings,
    }


class AsyncAuditorTests(unittest.TestCase):
    def test_clean_lane_is_independent_and_deterministic(self):
        inputs = [audit(), snapshot(), lease()]
        before = copy.deepcopy(inputs)
        first = build_async_audit(*inputs)
        second = build_async_audit(*inputs)

        self.assertEqual(first, second)
        self.assertEqual(before, inputs)
        self.assertEqual("ASYNC_AUDIT", first["lane"])
        self.assertFalse(first["interaction_blocking"])
        self.assertEqual("READ_ONLY", first["user_artifact_policy"])
        self.assertEqual([], first["artifact_operations"])
        self.assertEqual([], first["proposals"])
        self.assertEqual([], validate_async_audit(first))

    def test_findings_become_triage_issue_and_duplicates_are_suppressed(self):
        findings = [
            {"code": "stale-pin", "subject": "self-model", "observed": {"kind": "metadata"}},
            {"code": "stale-pin", "subject": "self-model", "observed": {"kind": "metadata"}},
        ]
        artifacts = [{"artifact_id": "artifact:answer-001", "file_id": "opaque-file-001"}]
        before = copy.deepcopy(artifacts)
        result = build_async_audit(
            audit(findings),
            snapshot(),
            lease(),
            user_artifacts=artifacts,
            repository_scopes={"self-model": ["entities", "README.md"]},
        )

        self.assertEqual(before, artifacts)
        self.assertEqual(1, len(result["proposals"]))
        proposal = result["proposals"][0]
        self.assertEqual("ISSUE", proposal["kind"])
        self.assertEqual("TRIAGE", proposal["status"])
        self.assertEqual("NOT_RUN", proposal["quality_gate_status"])
        self.assertEqual("ISSUE_CANDIDATE", proposal["delivery"]["type"])
        self.assertNotIn("observed", proposal)
        self.assertNotIn("content", json.dumps(result))
        self.assertEqual([], validate_async_audit(result))

    def test_passed_quality_gate_allows_only_a_draft_pr_plan(self):
        result = build_async_audit(
            audit([{"code": "contract-drift", "subject": "self-model", "observed": {"kind": "schema"}}]),
            snapshot(),
            lease(),
            quality_gates={"self-model": {"status": "PASSED", "observed_commit": SELF_COMMIT}},
        )
        proposal = result["proposals"][0]

        self.assertEqual("DRAFT_PR", proposal["kind"])
        self.assertEqual("READY", proposal["status"])
        self.assertEqual("DRAFT_PR_PLAN", proposal["delivery"]["type"])
        self.assertTrue(proposal["human_gate"])
        self.assertEqual([], proposal["artifact_operations"])
        self.assertEqual([], validate_async_audit(result))

    def test_failed_gate_stays_blocked_issue_and_expired_lease_is_rejected(self):
        result = build_async_audit(
            audit([{"code": "privacy", "subject": "self-model", "observed": {"kind": "boundary"}}]),
            snapshot(),
            lease(),
            quality_gates={"self-model": {"status": "FAILED", "observed_commit": SELF_COMMIT}},
        )
        proposal = result["proposals"][0]
        self.assertEqual(("ISSUE", "BLOCKED"), (proposal["kind"], proposal["status"]))

        with self.assertRaisesRegex(AsyncAuditorError, "expired"):
            build_async_audit(
                audit(),
                snapshot(),
                lease(expires_at="2026-08-11T20:00:00+09:00"),
            )

    def test_lane_snapshot_and_raw_artifact_boundaries_are_rejected(self):
        with self.assertRaisesRegex(AsyncAuditorError, "independent ASYNC_AUDIT"):
            build_async_audit(audit(), snapshot(), lease(lane="INTERACTION"))
        with self.assertRaisesRegex(AsyncAuditorError, "forbidden"):
            build_async_audit(
                audit(),
                snapshot(),
                lease(),
                user_artifacts=[{"artifact_id": "artifact:answer-001", "content": "must not enter audit"}],
            )
        dirty = snapshot()
        dirty["repositories"][0]["dirty"] = True
        with self.assertRaisesRegex(AsyncAuditorError, "not qualified"):
            build_async_audit(audit(), dirty, lease())

    def test_schema_declares_lane_and_zero_artifact_operations(self):
        schema = json.loads((ROOT / "schemas/async-audit.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("async-audit/v1", schema["properties"]["contract_version"]["const"])
        self.assertEqual("ASYNC_AUDIT", schema["properties"]["lane"]["const"])
        self.assertEqual([], schema["properties"]["artifact_operations"]["const"])
        self.assertIn("proposal", schema["$defs"])


if __name__ == "__main__":
    unittest.main()
