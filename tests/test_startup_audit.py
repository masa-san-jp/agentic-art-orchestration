from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("startup_tool", ROOT / "tools/startup.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class StartupAuditTests(unittest.TestCase):
    def setUp(self):
        self.manifest = MODULE.load_manifest()
        self.snapshot_path = ROOT / "data/snapshot.json"
        self.snapshot_before = self.snapshot_path.read_bytes()
        self.repository_ids = [repository["id"] for repository in self.manifest["repositories"]]
        self.clean_guard = {
            "blocked_count": 0,
            "repositories": [
                {"id": repository_id, "blocked": False, "reason_codes": []}
                for repository_id in self.repository_ids
            ],
        }
        self.clean_status = {"blockers": [], "drift": {"items": []}}
        self.clean_audit = {"findings": []}
        self.clean_security = {"findings": []}

        def clean_observation(repository, qualified_commit, remote, timestamp):
            return {
                "repository": repository["id"],
                "qualified_commit": qualified_commit,
                "remote_observed_commit": qualified_commit,
                "observation_timestamp": timestamp,
                "drift": "CLEAN",
                "pinned_for_use": True,
            }

        self.clean_observation = clean_observation

    def build(self, *, audit=None, security=None, guard=None, observation=None):
        audit_result = audit or self.clean_audit
        security_result = security or self.clean_security
        guard_result = guard or self.clean_guard
        patches = [
            patch.object(MODULE, "observe_repository", side_effect=observation or self.clean_observation),
            patch.object(MODULE, "guard_workspace", return_value=guard_result),
            patch.object(MODULE.status_tool, "build_status", return_value=self.clean_status),
            patch.object(MODULE.audit_tool, "build_audit", return_value=audit_result),
            patch.object(MODULE.security_tool, "audit_boundary", return_value=security_result),
            patch.object(MODULE.audit_tool, "_load_signals_and_requirements", return_value=([], [])),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            return MODULE.build_startup_report(
                self.manifest,
                self.snapshot_path,
                run_id="startup-audit-unit",
            )

    def test_noncritical_findings_allow_parent_control_plane_with_reason_codes(self):
        def update_observation(repository, qualified_commit, remote, timestamp):
            record = self.clean_observation(repository, qualified_commit, remote, timestamp)
            if repository["id"] == self.repository_ids[0]:
                record["remote_observed_commit"] = "b" * 40
                record["drift"] = "UPDATE_CANDIDATE"
            return record

        report = self.build(
            audit={"findings": [{"code": "untested-boundary", "subject": "runtime"}]},
            observation=update_observation,
        )
        statuses = {item["capability"]: item["status"] for item in report["capabilities"]}
        self.assertEqual("READY_WITH_FINDINGS", report["status"])
        self.assertEqual("ALLOWED", statuses["qualified_knowledge_read"])
        self.assertEqual("ALLOWED", statuses["branch_commit_pull_request"])
        self.assertEqual("BLOCKED", statuses["merge_release_tag"])
        self.assertEqual("RESTRICTED", statuses["drive_create"])
        self.assertEqual("BLOCKED", statuses["child_repository_mutation"])
        parent = next(item for item in report["capabilities"] if item["capability"] == "branch_commit_pull_request")
        self.assertEqual(
            ["audit_finding", "remote_update_candidate", "untested-boundary"],
            parent["reason_codes"],
        )

    def test_other_noncritical_findings_allow_parent_control_plane(self):
        audit = {"findings": [{"code": "untested-boundary", "subject": "runtime"}]}
        report = self.build(audit=audit)
        statuses = {item["capability"]: item["status"] for item in report["capabilities"]}
        self.assertEqual("ALLOWED", statuses["branch_commit_pull_request"])
        self.assertEqual("BLOCKED", statuses["merge_release_tag"])

    def test_validate_report_rejects_unsafe_capability_overrides(self):
        report = self.build()
        for capability in (
            "child_repository_mutation",
            "drive_update_delete_share",
            "github_issue_update_close_delete_comment_label",
        ):
            candidate = copy.deepcopy(report)
            next(item for item in candidate["capabilities"] if item["capability"] == capability)["status"] = "ALLOWED"
            errors = MODULE.validate_report(candidate)
            self.assertTrue(any("always-blocked capabilities" in error for error in errors), capability)

    def test_validate_report_rejects_empty_ready_with_findings(self):
        report = self.build()
        report["status"] = "READY_WITH_FINDINGS"
        next(item for item in report["capabilities"] if item["capability"] == "branch_commit_pull_request")["status"] = "ALLOWED"
        errors = MODULE.validate_report(report)
        self.assertIn("READY_WITH_FINDINGS", " ".join(errors))

    def test_validate_report_rejects_nonblocked_critical_finding(self):
        report = self.build()
        report["status"] = "READY_WITH_FINDINGS"
        report["findings"] = [{"code": "credential", "severity": "CRITICAL", "source": "security"}]
        errors = MODULE.validate_report(report)
        self.assertTrue(any("critical finding" in error for error in errors))

    def test_noncritical_findings_are_ready_with_deduplicated_issue_candidates(self):
        audit = {"findings": [{"code": "untested-boundary", "subject": "runtime"}]}
        report = self.build(audit=audit)
        self.assertEqual("READY_WITH_FINDINGS", report["status"])
        self.assertEqual("PASSED", report["workspace_guard"]["status"])
        self.assertIn("audit_finding", {finding["code"] for finding in report["findings"]})
        self.assertEqual(1, len(report["issue_candidates"]))
        candidate = report["issue_candidates"][0]
        self.assertEqual("untested-boundary", candidate["finding_code"])
        self.assertFalse(candidate["creation_permitted"])
        self.assertTrue(candidate["human_gate"])
        self.assertEqual("NONE", candidate["side_effect"])
        self.assertEqual(
            len(report["issue_candidates"]),
            len({candidate["deduplication_key"] for candidate in report["issue_candidates"]}),
        )

    def test_security_finding_blocks_and_restricts_all_capabilities(self):
        security = {"findings": [{"code": "credential"}]}
        report = self.build(security=security)
        self.assertEqual("BLOCKED", report["status"])
        self.assertEqual("BLOCKED", report["ordered_steps"][7]["status"])
        self.assertIn("credential", {finding["code"] for finding in report["findings"]})
        self.assertTrue(all(item["status"] == "BLOCKED" for item in report["capabilities"]))
        self.assertTrue(all(not item["creation_permitted"] for item in report["issue_candidates"]))

    def test_critical_audit_finding_blocks(self):
        audit = {"findings": [{"code": "schema-drift", "severity": "error", "subject": "contract"}]}
        report = self.build(audit=audit)
        self.assertEqual("BLOCKED", report["status"])
        self.assertIn("schema-drift", {finding["code"] for finding in report["findings"]})
        self.assertTrue(all(item["status"] == "BLOCKED" for item in report["capabilities"]))

    def test_privacy_audit_finding_is_critical(self):
        audit = {"findings": [{"code": "consent", "severity": "error", "subject": "self-model"}]}
        report = self.build(audit=audit)
        self.assertEqual("BLOCKED", report["status"])
        self.assertIn("consent", {finding["code"] for finding in report["findings"]})
        self.assertTrue(all(item["status"] == "BLOCKED" for item in report["capabilities"]))

    def test_workspace_guard_failure_is_critical_and_report_is_metadata_only(self):
        guard = copy.deepcopy(self.clean_guard)
        guard["blocked_count"] = 1
        guard["repositories"][0] = {
            "id": self.repository_ids[0],
            "blocked": True,
            "reason_codes": ["dirty"],
        }
        report = self.build(guard=guard)
        self.assertEqual("BLOCKED", report["status"])
        self.assertEqual(["dirty"], report["workspace_guard"]["finding_codes"])
        self.assertNotIn('"raw_conversation":', json.dumps(report))
        self.assertEqual(self.snapshot_before, self.snapshot_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
