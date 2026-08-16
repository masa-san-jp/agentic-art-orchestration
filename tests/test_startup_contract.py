from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "orchestration_validate", ROOT / "tools/validate.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class StartupContractTests(unittest.TestCase):
    def setUp(self):
        self.policy = yaml.safe_load(
            (ROOT / "config/startup-policy.yaml").read_text(encoding="utf-8")
        )
        self.schema = MODULE.load_json(ROOT / "schemas/startup-report.schema.json")

    def test_policy_and_report_contract_are_valid(self):
        self.assertEqual([], MODULE.validate_startup_contract(self.policy, self.schema))

    def test_startup_order_is_fail_closed(self):
        policy = copy.deepcopy(self.policy)
        steps = policy["startup"]["ordered_preflight"]
        steps[1], steps[2] = steps[2], steps[1]
        errors = MODULE.validate_startup_contract(policy, self.schema)
        self.assertTrue(any("ordered_preflight" in error for error in errors))

    def test_external_mutations_are_create_only(self):
        policy = copy.deepcopy(self.policy)
        policy["capabilities"][4]["allowed_outcomes"] = ["READY", "READY_WITH_FINDINGS"]
        errors = MODULE.validate_startup_contract(policy, self.schema)
        self.assertTrue(any("drive_create" in error for error in errors))

    def test_parent_control_plane_finding_policy_is_explicit(self):
        parent = next(item for item in self.policy["capabilities"] if item["id"] == "branch_commit_pull_request")
        self.assertEqual(["WARNING"], parent["allowed_finding_severities"])
        self.assertTrue(parent["require_nonempty_findings_for_ready_with_findings"])
        policy = copy.deepcopy(self.policy)
        next(item for item in policy["capabilities"] if item["id"] == "branch_commit_pull_request")["allowed_finding_severities"] = []
        errors = MODULE.validate_startup_contract(policy, self.schema)
        self.assertTrue(any("finding policy" in error for error in errors))

    def test_report_is_closed_and_metadata_only(self):
        properties = self.schema["properties"]
        self.assertFalse(self.schema["additionalProperties"])
        for forbidden in MODULE.STARTUP_FORBIDDEN_FIELDS:
            self.assertNotIn(forbidden, properties)

    def test_valid_report_fixture_matches_schema(self):
        repository_ids = [
            repository["id"]
            for repository in MODULE.load_yaml(ROOT / "config/repositories.yaml")["repositories"]
        ]
        timestamp = "2026-08-13T12:00:00+09:00"
        steps = [
            {
                "step_id": step_id,
                "status": "PASSED",
                "blocking": False,
                "finding_codes": [],
            }
            for step_id in MODULE.STARTUP_STEPS
        ]
        repositories = [
            {
                "repository": repository_id,
                "qualified_commit": "a" * 40,
                "remote_observed_commit": "a" * 40,
                "observation_timestamp": timestamp,
                "drift": "CLEAN",
                "pinned_for_use": True,
            }
            for repository_id in repository_ids
        ]
        capabilities = [
            {
                "capability": capability,
                "status": "ALLOWED" if capability in MODULE.STARTUP_CAPABILITIES[:6] or capability == "branch_commit_pull_request" else "BLOCKED",
                "reason_codes": [],
            }
            for capability in MODULE.STARTUP_CAPABILITIES
        ]
        report = {
            "contract_version": "startup-report/v1",
            "run_id": "startup-contract-fixture",
            "generated_at": timestamp,
            "profile": "initial-operations",
            "agent_client": "Codex",
            "status": "READY",
            "parent_commit": "b" * 40,
            "ordered_steps": steps,
            "repositories": repositories,
            "workspace_guard": {
                "status": "PASSED",
                "checked_repositories": repository_ids,
                "finding_codes": [],
            },
            "findings": [],
            "issue_candidates": [],
            "capabilities": capabilities,
            "remediation": [],
            "privacy": {
                "raw_conversation_stored": False,
                "credentials_stored": False,
                "raw_remote_response_stored": False,
                "drive_content_stored": False,
                "direct_identifiers_stored": False,
            },
            "remote_operations": [],
        }
        self.assertEqual([], MODULE._schema_errors(report, self.schema))
        report["unexpected"] = True
        self.assertTrue(any("unexpected" in error for error in MODULE._schema_errors(report, self.schema)))


if __name__ == "__main__":
    unittest.main()
