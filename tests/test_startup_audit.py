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

    def build(self, *, audit=None, security=None, guard=None):
        audit_result = audit or self.clean_audit
        security_result = security or self.clean_security
        guard_result = guard or self.clean_guard
        patches = [
            patch.object(MODULE, "observe_repository", side_effect=self.clean_observation),
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
