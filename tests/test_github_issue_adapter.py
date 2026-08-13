from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tools.github_issue_adapter import FixtureProvider, deliver
from tools.validate import load_json, load_yaml, validate_issue_delivery_contract


ROOT = Path(__file__).resolve().parents[1]


def manifest() -> dict:
    return load_yaml(ROOT / "config/repositories.yaml")


def explicit_candidate() -> dict:
    return {
        "candidate_id": "candidate:explicit-001",
        "source_kind": "explicit",
        "target_repository": "art-history",
        "summary_code": "request:add-art-evidence",
        "deduplication_key": "issue:art-history-evidence-001",
        "privacy_safe_summary": "Review the evidence coverage at the authoritative repository boundary.",
        "source_feedback_ids": ["feedback:interaction-001:002"],
        "acceptance": ["Review the evidence gap and preserve source references."],
        "creation_permitted": True,
        "human_gate": True,
        "side_effect": "NONE",
    }


def inferred_candidate() -> dict:
    candidate = explicit_candidate()
    candidate.update(
        {
            "candidate_id": "candidate:inferred-001",
            "source_kind": "inferred",
            "target_repository": "agentic-art-orchestration",
            "summary_code": "friction:repeated-context-request",
            "deduplication_key": "issue:inferred-context-001",
            "source_feedback_ids": ["feedback:interaction-001:001"],
            "inference": {"is_inferred": True, "hypothesis_status": "unconfirmed"},
            "confidence": "medium",
            "counterevidence_refs": ["interaction:001:outcome:002"],
        }
    )
    return candidate


class GithubIssueAdapterTests(unittest.TestCase):
    def test_plan_is_deterministic_and_has_no_remote_operations(self):
        candidate = explicit_candidate()
        first = deliver([candidate], manifest(), mode="plan", run_id="ISSUE-CREATE-001:test")
        second = deliver([candidate], manifest(), mode="plan", run_id="ISSUE-CREATE-001:test")
        self.assertEqual(first, second)
        self.assertEqual([], first["remote_operations"])
        self.assertEqual("PLANNED", first["records"][0]["status"])
        self.assertEqual("NONE", first["records"][0]["operation"])
        self.assertEqual("masa-san-jp/art-history-notes", first["records"][0]["target_full_name"])
        self.assertEqual([], [record for record in first["records"] if record["status"] == "BLOCKED"])

    def test_live_reuses_existing_issue_without_create(self):
        candidate = explicit_candidate()
        provider = FixtureProvider({"masa-san-jp/art-history-notes:issue:art-history-evidence-001": [{"number": 17, "url": "https://github.com/masa-san-jp/art-history-notes/issues/17"}]})
        result = deliver([candidate], manifest(), mode="live", provider=provider, run_id="ISSUE-CREATE-001:reuse")
        operation = result["records"][0]
        self.assertEqual("REUSED", operation["status"])
        self.assertEqual(17, operation["issue_number"])
        self.assertEqual([], provider.created)
        self.assertEqual("REUSE", operation["operation"])
        self.assertEqual("REUSE", result["remote_operations"][-1]["operation"])

    def test_live_creates_only_one_privacy_safe_issue(self):
        candidate = explicit_candidate()
        provider = FixtureProvider()
        result = deliver([candidate], manifest(), mode="live", provider=provider, run_id="ISSUE-CREATE-001:create")
        operation = result["records"][0]
        self.assertEqual("CREATED", operation["status"])
        self.assertEqual("CREATE", operation["operation"])
        self.assertEqual(1, len(provider.created))
        body_hash_record = provider.created[0]
        self.assertNotIn("raw_conversation", json.dumps(result))
        self.assertEqual("masa-san-jp/art-history-notes", body_hash_record["repository"])
        self.assertEqual([], [record for record in result["records"] if record["status"] == "BLOCKED"])

    def test_same_fixture_provider_reuses_created_issue_on_retry(self):
        provider = FixtureProvider()
        first = deliver([explicit_candidate()], manifest(), mode="live", provider=provider, run_id="ISSUE-CREATE-001:retry")
        second = deliver([explicit_candidate()], manifest(), mode="live", provider=provider, run_id="ISSUE-CREATE-001:retry")
        self.assertEqual("CREATED", first["records"][0]["status"])
        self.assertEqual("REUSED", second["records"][0]["status"])
        self.assertEqual(1, len(provider.created))
        self.assertEqual(["READ", "CREATE"], [item["operation"] for item in first["remote_operations"]])
        self.assertEqual(["READ", "REUSE"], [item["operation"] for item in second["remote_operations"]])

    def test_inferred_candidate_preserves_unconfirmed_boundary_in_issue_body(self):
        provider = FixtureProvider()
        result = deliver([inferred_candidate()], manifest(), mode="live", provider=provider, run_id="ISSUE-CREATE-001:inferred")
        self.assertEqual("CREATED", result["records"][0]["status"])
        body = provider.created[0]
        self.assertIn("unconfirmed", body["body"])
        self.assertIn("Target authority", body["body"])
        self.assertIn("Prohibited data scan: `PASS`", body["body"])
        self.assertEqual("masa-san-jp/agentic-art-orchestration", body["repository"])
        self.assertTrue(result["records"][0]["inference"]["is_inferred"])
        self.assertEqual("unconfirmed", result["records"][0]["inference"]["hypothesis_status"])

    def test_multiple_existing_issues_fail_closed_without_create(self):
        candidate = explicit_candidate()
        provider = FixtureProvider(
            {
                "masa-san-jp/art-history-notes:issue:art-history-evidence-001": [
                    {"number": 17, "url": "https://github.com/masa-san-jp/art-history-notes/issues/17"},
                    {"number": 18, "url": "https://github.com/masa-san-jp/art-history-notes/issues/18"},
                ]
            }
        )
        result = deliver([candidate], manifest(), mode="live", provider=provider, run_id="ISSUE-CREATE-001:ambiguous")
        self.assertEqual("BLOCKED", result["records"][0]["status"])
        self.assertEqual("NONE", result["records"][0]["operation"])
        self.assertEqual([], provider.created)

    def test_duplicate_key_merges_source_refs_and_conflict_is_blocked(self):
        first = explicit_candidate()
        second = copy.deepcopy(first)
        second["candidate_id"] = "candidate:explicit-002"
        second["source_feedback_ids"] = ["feedback:interaction-001:003"]
        conflict = copy.deepcopy(first)
        conflict["candidate_id"] = "candidate:conflict-001"
        conflict["summary_code"] = "request:conflicting-summary"
        result = deliver([second, conflict, first], manifest(), mode="plan", run_id="ISSUE-CREATE-001:dedupe")
        self.assertEqual(1, len([record for record in result["records"] if record["status"] == "PLANNED"]))
        self.assertEqual(["feedback:interaction-001:002", "feedback:interaction-001:003"], [record for record in result["records"] if record["status"] == "PLANNED"][0]["source_refs"])
        self.assertEqual(1, len([record for record in result["records"] if record["status"] == "BLOCKED"]))

    def test_unallowlisted_and_raw_candidates_are_blocked_without_side_effect(self):
        candidate = explicit_candidate()
        candidate["target_repository"] = "unknown-repository"
        raw = explicit_candidate()
        raw["candidate_id"] = "candidate:raw-001"
        raw["message"] = "must never cross the boundary"
        result = deliver([candidate, raw], manifest(), mode="plan", run_id="ISSUE-CREATE-001:blocked")
        self.assertEqual([], [record for record in result["records"] if record["status"] == "PLANNED"])
        self.assertEqual(2, len([record for record in result["records"] if record["status"] == "BLOCKED"]))
        self.assertEqual([], result["remote_operations"])

    def test_live_requires_explicit_confirmation_at_cli(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/github_issue_adapter.py"), "--fixture", "--mode", "live"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("--confirm-live", result.stderr)

    def test_plan_alias_is_supported(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/github_issue_adapter.py"), "--fixture", "--plan", "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode)
        self.assertIn('"mode": "plan"', result.stdout)

    def test_policy_and_schema_are_closed_and_create_only(self):
        policy = load_yaml(ROOT / "config/issue-delivery-policy.yaml")
        schema = load_json(ROOT / "schemas/github-issue-delivery.schema.json")
        self.assertEqual({"READ", "CREATE"}, set(policy["allowed_operations"]))
        self.assertIn("UPDATE", policy["forbidden_operations"])
        self.assertTrue(policy["human_confirmation_required"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual({"PLAN", "LIVE"}, set(schema["properties"]["mode"]["enum"]))
        self.assertEqual([], validate_issue_delivery_contract(policy, schema, manifest()))

    def test_untrusted_confidence_is_rejected_before_live_create(self):
        candidate = explicit_candidate()
        candidate["confidence"] = "conversation body must not be copied"
        provider = FixtureProvider()
        result = deliver([candidate], manifest(), mode="live", provider=provider, run_id="ISSUE-CREATE-001:confidence")
        self.assertEqual("BLOCKED", result["records"][0]["status"])
        self.assertEqual([], provider.created)


if __name__ == "__main__":
    unittest.main()
