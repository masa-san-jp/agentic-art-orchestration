from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tools.pr_triage import CHANGE_CLASSES, RECOMMENDATIONS, build_report
from tools.validate import _schema_errors, load_json, load_yaml


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/pr-triage/open-prs.json"
QUEUE = ROOT / "execution/task-queue.yaml"
SCHEMA = ROOT / "schemas/pr-triage-report.schema.json"


class PRTriageTests(unittest.TestCase):
    def test_fixture_covers_all_recommendations_and_change_classes(self):
        payload = load_json(FIXTURE)
        report = build_report(payload, QUEUE)
        self.assertEqual("pr-triage-report/v1", report["contract_version"])
        self.assertEqual(7, report["summary"]["repository_count"])
        self.assertEqual(6, report["summary"]["pull_request_count"])
        self.assertEqual(set(RECOMMENDATIONS), {
            item["recommendation"] for item in report["pull_requests"]
        })
        self.assertEqual(set(CHANGE_CLASSES), {
            item["change_class"] for item in report["pull_requests"]
        })
        self.assertEqual([], _schema_errors(report, load_json(SCHEMA), "fixture report"))

    def test_repeated_generation_is_byte_identical_and_input_is_unchanged(self):
        payload = load_json(FIXTURE)
        original = copy.deepcopy(payload)
        first = build_report(payload, QUEUE)
        second = build_report(payload, QUEUE)
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            json.dumps(second, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        self.assertEqual(original, payload)

    def test_report_is_metadata_only_and_has_no_write_operation(self):
        report = build_report(load_json(FIXTURE), QUEUE)
        rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
        for forbidden in ('"body"', '"diff"', '"comment"', '"raw"', '"credential"'):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual([], report["remote_operations"])
        source = (ROOT / "tools/pr_triage.py").read_text(encoding="utf-8")
        for forbidden_command in ("gh pr merge", "gh pr close", "gh pr comment", "git push", "git rebase"):
            self.assertNotIn(forbidden_command, source)

    def test_recommendation_precedence_preserves_unknowns(self):
        payload = load_json(FIXTURE)
        conflict = copy.deepcopy(payload["pull_requests"][0])
        conflict["number"] = 999
        conflict["url"] = "https://github.com/masa-san-jp/agentic-art-orchestration/pull/999"
        conflict["checks"] = {"status": "RED", "total": 1, "passed": 0, "failed": 1, "pending": 0}
        conflict["conflict"] = "YES"
        report = build_report({**payload, "pull_requests": [conflict]}, QUEUE)
        self.assertEqual("NEEDS_REBASE", report["pull_requests"][0]["recommendation"])

        unknown = copy.deepcopy(payload["pull_requests"][4])
        unknown["number"] = 998
        unknown["url"] = "https://github.com/masa-san-jp/marketing-trends-notes/pull/998"
        unknown["checks"] = {"status": "UNKNOWN", "total": 0, "passed": 0, "failed": 0, "pending": 0}
        report = build_report({**payload, "pull_requests": [unknown]}, QUEUE)
        self.assertEqual("HUMAN_JUDGMENT", report["pull_requests"][0]["recommendation"])

    def test_every_merge_class_requires_human_approval_and_disables_auto_merge(self):
        gates = load_yaml(ROOT / "config/human-gates.yaml")
        self.assertEqual(
            {"CLASS_RECORD", "CLASS_DOCS", "CLASS_CODE", "CLASS_CONTRACT"},
            set(gates["merge_classes"]),
        )
        for definition in gates["merge_classes"].values():
            self.assertFalse(definition["auto_merge"])
            self.assertTrue(definition["human_approval_required"])
        self.assertIn("merge", gates["human_operations"])
        self.assertEqual("BLOCKED_HUMAN", gates["default_status"])

    def test_cli_fixture_check_is_read_only_and_deterministic(self):
        before = QUEUE.read_bytes()
        command = [
            sys.executable, str(ROOT / "tools/pr_triage.py"),
            "--fixture", str(FIXTURE), "--check",
        ]
        first = subprocess.run(command, capture_output=True, text=True, check=False)
        second = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(before, QUEUE.read_bytes())


if __name__ == "__main__":
    unittest.main()
