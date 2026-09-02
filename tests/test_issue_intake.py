from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tools.issue_intake import _live_input, build_report
from tools.validate import _schema_errors, load_json, load_yaml


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/issue-intake/open-issues.json"
QUEUE = ROOT / "execution/task-queue.yaml"
SCHEMA = ROOT / "schemas/issue-intake-report.schema.json"


class IssueIntakeTests(unittest.TestCase):
    def test_fixture_report_is_schema_valid_and_omits_issue_body(self):
        payload = load_json(FIXTURE)
        source = {**payload["source"], "repository": payload["repository"]}
        report = build_report(payload["issues"], source, QUEUE)
        by_number = {issue["number"]: issue for issue in report["issues"]}
        self.assertEqual("issue-intake-report/v1", report["contract_version"])
        self.assertEqual("ALREADY_QUEUED", by_number[113]["recommendation"])
        self.assertEqual("REGISTER_BACKLOG", by_number[999]["recommendation"])
        self.assertEqual("UNQUEUED_NEEDS_SSOT", by_number[998]["recommendation"])
        self.assertEqual([], _schema_errors(report, load_json(SCHEMA), "fixture report"))
        rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("validator passes from a fresh clone", rendered)
        self.assertNotIn('"body"', rendered)

    def test_repeated_generation_is_byte_identical_and_inputs_are_unchanged(self):
        payload = load_json(FIXTURE)
        original = copy.deepcopy(payload)
        source = {**payload["source"], "repository": payload["repository"]}
        first = build_report(payload["issues"], source, QUEUE)
        second = build_report(payload["issues"], source, QUEUE)
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            json.dumps(second, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        self.assertEqual(original, payload)

    def test_cli_check_is_byte_identical_and_queue_is_read_only(self):
        before = QUEUE.read_bytes()
        command = [sys.executable, str(ROOT / "tools/issue_intake.py"), "--fixture", str(FIXTURE), "--check"]
        first = subprocess.run(command, capture_output=True, text=True, check=False)
        second = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(before, QUEUE.read_bytes())

    def test_unknown_repository_is_needs_ssot_without_domain_decision(self):
        payload = load_json(FIXTURE)
        issue = copy.deepcopy(payload["issues"][1])
        issue["number"] = 997
        issue["url"] = "https://github.com/example/unknown/issues/997"
        issue["repository"] = "example/unknown"
        source = {**payload["source"], "repository": payload["repository"]}
        report = build_report([issue], source, QUEUE)
        self.assertEqual("UNQUEUED_NEEDS_SSOT", report["issues"][0]["recommendation"])
        self.assertIn("target_repository", report["issues"][0]["ssot"]["missing"])

    def test_empty_queue_rule_and_ssot_minimum_are_documented(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        runbook = (ROOT / "docs/operator-runbook.md").read_text(encoding="utf-8")
        self.assertIn("READYも依存完了済みBACKLOGもない場合", agents)
        self.assertIn("観測可能な受入条件", agents)
        self.assertIn("対象repository", agents)
        self.assertIn("検証コマンド", agents)
        self.assertIn("human gateの有無", agents)
        self.assertIn("空queue時のIssue intake", runbook)
        self.assertIn("REGISTER_BACKLOG", runbook)
        self.assertIn("UNQUEUED_NEEDS_SSOT", runbook)

    def test_first_application_registers_qualified_issue_once(self):
        queue = load_yaml(QUEUE)
        matches = [
            task for task in queue["tasks"]
            if task.get("issue_ssot") == "https://github.com/masa-san-jp/agentic-art-orchestration/issues/117"
        ]
        self.assertEqual(1, len(matches))
        self.assertEqual("HARNESS-PR-TRIAGE-001", matches[0]["id"])
        self.assertIn(matches[0]["status"], {"BACKLOG", "READY", "IN_PROGRESS", "DONE"})
        self.assertEqual(["HARNESS-REALCHAIN-REBASE-001"], matches[0]["depends_on"])

    def test_live_input_scopes_metadata_and_body_to_each_repository(self):
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[2] == "list":
                return subprocess.CompletedProcess(command, 0, '[{"number": 7, "title": "T", "url": "https://github.com/o/r/issues/7"}]', "")
            return subprocess.CompletedProcess(command, 0, '{"body": "## Acceptance criteria\\n- [ ] do\\n## Checks\\n```bash\\ntrue\\n```\\n## Human gate\\nnone"}', "")

        with patch("tools.issue_intake.subprocess.run", side_effect=fake_run):
            source, issues = _live_input(["o/r"], "2026-09-02T00:00:00Z")

        self.assertEqual("live", source["kind"])
        self.assertEqual("T", issues[0]["title"])
        self.assertEqual("## Acceptance criteria\n- [ ] do\n## Checks\n```bash\ntrue\n```\n## Human gate\nnone", issues[0]["body"])
        self.assertEqual(2, len(calls))
        self.assertEqual(["gh", "issue", "list"], calls[0][:3])
        self.assertIn("--repo", calls[0])
        self.assertNotIn("body", calls[0])
        self.assertEqual(["gh", "issue", "view"], calls[1][:3])
        self.assertIn("--repo", calls[1])
        self.assertEqual("o/r", calls[1][calls[1].index("--repo") + 1])


if __name__ == "__main__":
    unittest.main()
