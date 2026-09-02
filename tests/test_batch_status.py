from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.batch_status import (
    aggregate_report,
    scan_workspace,
    validate_batch_report_event,
)


COMMIT = "a" * 40


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _write_yaml(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _event(event_id: str, event_type: str, **values) -> dict:
    return {
        "contract_version": "batch-report-event/v1",
        "event_id": event_id,
        "run_id": "batch-run-001",
        "event_type": event_type,
        "project_id": "project-001",
        "repository": "agentic-art-research",
        "source_commit": COMMIT,
        "observed_at": "2026-08-27T08:30:00+09:00",
        "attempt": 1,
        "duration_seconds": None,
        "token_count": None,
        **values,
    }


class BatchStatusTests(unittest.TestCase):
    def _workspace(self) -> Path:
        temporary = Path(tempfile.mkdtemp(prefix="batch-status-"))
        projects = temporary / "projects"
        cases = {
            "not-started": {"status": "PENDING", "tasks": [{"status": "PENDING"}, {"status": "PENDING"}]},
            "in-progress": {"status": "RUNNING", "tasks": [{"status": "SUCCEEDED"}, {"status": "PENDING"}]},
            "terminal": {"status": "COMPLETE", "tasks": [{"status": "SUCCEEDED"}]},
            "handoff": {"status": "COMPLETE", "tasks": [{"status": "SUCCEEDED"}]},
            "planned": {"status": "COMPLETE", "tasks": [{"status": "SUCCEEDED"}]},
        }
        for slug, state in cases.items():
            state["project_id"] = slug
            _write_json(projects / slug / "07_runtime" / "research-state.json", state)
        _write_yaml(
            projects / "handoff" / "05_production" / "production-handoff.yaml",
            "status: ACCEPTED\ncontract_version: production-handoff/v1\n",
        )
        _write_yaml(
            projects / "planned" / "05_production" / "production-handoff.yaml",
            "status: ACCEPTED\ncontract_version: production-handoff/v1\n",
        )
        _write_yaml(
            projects / "planned" / "03_plan" / "production-plan.yaml",
            "readiness:\n  startable: true\n",
        )

        repository = temporary / "agentic-art-research"
        repository.mkdir()
        subprocess.run(["git", "-C", str(repository), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repository), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repository), "config", "user.name", "Batch Test"], check=True)
        (repository / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repository), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repository), "commit", "-q", "-m", "fixture"], check=True)
        head = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
        subprocess.run(["git", "-C", str(repository), "update-ref", "refs/remotes/origin/main", head], check=True)
        return temporary

    def test_scan_reports_five_stages_and_git_origin_difference(self):
        workspace = self._workspace()
        first = scan_workspace(workspace)
        second = scan_workspace(workspace)

        self.assertEqual(first, second)
        self.assertEqual(
            {"NOT_STARTED", "IN_PROGRESS", "TERMINAL", "HANDOFF", "PLANNED"},
            {project["stage"] for project in first["projects"]},
        )
        progress = {project["project_id"]: project for project in first["projects"]}
        self.assertEqual((1, 2), (progress["in-progress"]["task_completed"], progress["in-progress"]["task_total"]))
        repository = first["repositories"][0]
        self.assertEqual("agentic-art-research", repository["repository_id"])
        self.assertEqual(0, repository["origin_ahead"])
        self.assertTrue(first["read_only"])

    def test_scan_read_only_tree_hash_is_unchanged(self):
        workspace = self._workspace()
        before = _tree_hash(workspace)
        scan_workspace(workspace)
        after = _tree_hash(workspace)
        self.assertEqual(before, after)

    def test_report_aggregates_events_and_preserves_unmeasured_values(self):
        with tempfile.TemporaryDirectory(prefix="batch-report-") as directory:
            path = Path(directory) / "batch-report.jsonl"
            events = [
                _event("event-001", "STARTED"),
                _event("event-002", "COMPLETED"),
                _event("event-003", "FAILED"),
                _event("event-004", "RETRY"),
                _event("event-005", "DURATION", duration_seconds=2.5),
            ]
            path.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events), encoding="utf-8")
            summary = aggregate_report(path)

        self.assertEqual(5, summary["event_count"])
        self.assertEqual({"起動": 1, "完了": 1, "失敗": 1, "再試行": 1}, summary["counts"])
        self.assertEqual(2.5, summary["duration"]["total_seconds"])
        self.assertEqual("未計測", summary["tokens"]["display"])

    def test_report_rejects_unknown_fields_and_unmeasured_special_events(self):
        invalid = _event("event-001", "STARTED")
        invalid["unexpected"] = True
        self.assertTrue(validate_batch_report_event(invalid))

        invalid_duration = _event("event-002", "DURATION")
        self.assertTrue(validate_batch_report_event(invalid_duration))

    def test_report_rejects_duplicate_event_ids(self):
        with tempfile.TemporaryDirectory(prefix="batch-report-duplicate-") as directory:
            path = Path(directory) / "batch-report.jsonl"
            event = _event("event-001", "STARTED")
            line = json.dumps(event, sort_keys=True) + "\n"
            path.write_text(line + line, encoding="utf-8")
            with self.assertRaises(ValueError):
                aggregate_report(path)


if __name__ == "__main__":
    unittest.main()
