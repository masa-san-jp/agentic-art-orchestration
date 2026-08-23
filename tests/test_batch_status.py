from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.batch_status import STAGES, summarise_report, survey
from tools.validate import validate_batch_report_event


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


class SurveyTests(unittest.TestCase):
    """A hundred projects cannot be asked where they are one at a time."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "workspace"
        self.projects = self.workspace / "agentic-art-research" / "projects"
        self.projects.mkdir(parents=True)
        self.output = Path(self.temporary.name) / "out"
        self.addCleanup(self.temporary.cleanup)

    def _project(self, slug: str, succeeded: int, total: int, *, status: str = "COLLECTING",
                 handoff: str | None = None, plan_startable: bool | None = None) -> None:
        project = self.projects / slug
        (project / "07_runtime").mkdir(parents=True)
        tasks = {
            f"TASK{index:03d}": {"status": "SUCCEEDED" if index <= succeeded else "PENDING"}
            for index in range(1, total + 1)
        }
        (project / "07_runtime/research-state.json").write_text(
            json.dumps({"status": status, "task_runtime": {"tasks": tasks}}), encoding="utf-8")
        if handoff is not None:
            (project / "05_production").mkdir(parents=True)
            (project / "05_production/production-handoff.yaml").write_text(
                f"status: {handoff}\n", encoding="utf-8")
        if plan_startable is not None:
            plan_dir = self.output / "production" / slug / "03_plan"
            plan_dir.mkdir(parents=True)
            (plan_dir / "production-plan.yaml").write_text(
                json.dumps({"readiness": {"startable": plan_startable}}), encoding="utf-8")

    def test_each_project_lands_in_exactly_one_named_stage(self):
        self._project("untouched", 0, 9)
        self._project("halfway", 4, 9)
        self._project("finished", 9, 9, status="COMPLETE")
        self._project("handed-over", 9, 9, status="COMPLETE", handoff="READY")
        self._project("planned", 9, 9, status="COMPLETE", handoff="READY", plan_startable=True)

        result = survey(self.workspace, self.output)

        stages = {item["slug"]: item["stage"] for item in result["projects"]}
        self.assertEqual("NOT_STARTED", stages["untouched"])
        self.assertEqual("IN_PROGRESS", stages["halfway"])
        self.assertEqual("TERMINAL", stages["finished"])
        self.assertEqual("HANDOFF", stages["handed-over"])
        self.assertEqual("PLANNED", stages["planned"])

    def test_the_counts_add_up_to_the_projects(self):
        self._project("a", 0, 3)
        self._project("b", 2, 3)

        result = survey(self.workspace, self.output)

        self.assertEqual(len(result["projects"]), sum(result["stage_counts"][stage] for stage in STAGES))

    def test_progress_is_reported_as_a_fraction_of_the_real_task_count(self):
        self._project("partial", 4, 9)

        result = survey(self.workspace, self.output)

        self.assertEqual((4, 9), (result["projects"][0]["tasks_done"], result["projects"][0]["tasks_total"]))

    def test_looking_does_not_move_anything(self):
        self._project("a", 2, 3, handoff="READY")
        before = _tree_hash(self.workspace)

        survey(self.workspace, self.output)

        self.assertEqual(before, _tree_hash(self.workspace))


class ReportSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "batch-report.jsonl"
        self.addCleanup(self.temporary.cleanup)

    def _write(self, events: list[dict]) -> None:
        self.path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")

    def test_launches_retries_and_failures_are_counted_separately(self):
        self._write([
            {"event_id": "1", "event_type": "AGENT_LAUNCHED", "occurred_at": "2026-08-23T00:00:00+09:00"},
            {"event_id": "2", "event_type": "TASK_RETRIED", "occurred_at": "2026-08-23T00:01:00+09:00"},
            {"event_id": "3", "event_type": "TASK_FAILED", "occurred_at": "2026-08-23T00:02:00+09:00"},
        ])

        summary = summarise_report(self.path)

        self.assertEqual((1, 1, 1), (summary["launches"], summary["retries"], summary["failures"]))

    def test_a_run_that_reported_no_tokens_is_unmeasured_not_zero(self):
        self._write([{"event_id": "1", "event_type": "AGENT_LAUNCHED", "occurred_at": "2026-08-23T00:00:00+09:00"}])

        summary = summarise_report(self.path)

        self.assertIsNone(summary["tokens_total"])
        self.assertTrue(summary["unmeasured_note"])

    def test_reported_tokens_are_totalled_and_the_note_goes_away(self):
        self._write([{"event_id": "1", "event_type": "AGENT_LAUNCHED",
                      "occurred_at": "2026-08-23T00:00:00+09:00", "tokens": 120}])

        summary = summarise_report(self.path)

        self.assertEqual(120, summary["tokens_total"])
        self.assertIsNone(summary["unmeasured_note"])

    def test_a_missing_report_summarises_to_nothing_rather_than_failing(self):
        summary = summarise_report(self.path.parent / "absent.jsonl")

        self.assertEqual(0, summary["event_count"])


class ReportEventContractTests(unittest.TestCase):
    def test_a_complete_event_validates(self):
        event = {"event_id": "E1", "event_type": "AGENT_LAUNCHED",
                 "occurred_at": "2026-08-23T00:00:00+09:00", "project_id": "project/a", "tokens": 10}

        self.assertEqual([], validate_batch_report_event(event))

    def test_an_unknown_event_type_is_refused(self):
        event = {"event_id": "E1", "event_type": "SOMETHING", "occurred_at": "2026-08-23T00:00:00+09:00"}

        self.assertTrue(validate_batch_report_event(event))

    def test_a_negative_token_count_is_refused(self):
        event = {"event_id": "E1", "event_type": "AGENT_LAUNCHED",
                 "occurred_at": "2026-08-23T00:00:00+09:00", "tokens": -1}

        self.assertTrue(validate_batch_report_event(event))


if __name__ == "__main__":
    unittest.main()
