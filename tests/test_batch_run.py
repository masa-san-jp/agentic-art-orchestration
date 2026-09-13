from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from tools.batch_run import (
    BatchRunError,
    _append_events,
    _event,
    _prepare_plan_projection,
    main,
    validate_batch_run,
)


class BatchRunContractTests(unittest.TestCase):
    def _summary(self) -> dict:
        sha = "a" * 64
        commit = "b" * 40
        return {
            "contract_version": "batch-run/v1",
            "run_id": "BATCH-001",
            "generated_at": "2026-08-27T00:00:00+09:00",
            "network": "DISABLED",
            "status": "PASSED",
            "requested_count": 1,
            "completed_count": 1,
            "failed_count": 0,
            "source_repositories": [
                {"repository": "art-history", "commit": commit, "record_count": 1},
                {"repository": "marketing-trends", "commit": commit, "record_count": 1},
                {"repository": "self-model", "commit": commit, "record_count": 1},
            ],
            "selection": {
                "candidate_space_hash": sha,
                "gate_report_hash": sha,
                "selection_hash": sha,
                "selected_count": 1,
                "unique_signal_tuple_count": 1,
                "self_diversity_status": "INSUFFICIENT_SELF_DIVERSITY",
                "source_commits": [commit, "c" * 40, "d" * 40],
            },
            "projects": [{
                "project_id": "batch-001",
                "candidate_id": "candidate:" + "1" * 16,
                "status": "PASSED",
                "research_locator": "run://BATCH-001/research/projects/batch-001",
                "production_locator": "run://BATCH-001/production/batch-001",
                "production_plan_sha256": sha,
                "brief_sha256": sha,
                "decision_log_sha256": sha,
            }],
            "acceptance": {
                "g1_production_plan_count": True,
                "g2_startable": True,
                "g3_structured_brief": True,
                "g4_no_human_authority": True,
                "g5_agent_recommended_decisions": True,
                "g6_append_only_report": True,
                "no_remote_operations": True,
                "no_child_mutations": True,
                "no_raw_data": True,
            },
            "report": {
                "locator": "run://BATCH-001/batch-report.jsonl",
                "sha256": sha,
                "event_count": 3,
                "completed_count": 1,
                "failed_count": 0,
                "retry_count": 0,
                "duration_seconds": 1.0,
                "token_count": None,
            },
            "remote_operations": [],
            "child_mutations": [],
            "delivery_contract": {"contract_version": "delivery-contract/v1", "target": "internal"},
            "delivery_completion": {"contract_version": "delivery-completion/v1", "target": "internal", "status": "INCOMPLETE", "missing": ["KNOWLEDGE_COMMIT"]},
        }

    def test_summary_is_closed_and_passed_counts_are_consistent(self) -> None:
        self.assertEqual([], validate_batch_run(self._summary()))
        invalid = copy.deepcopy(self._summary())
        invalid["acceptance"]["g4_no_human_authority"] = False
        self.assertTrue(validate_batch_run(invalid))

    def test_append_only_events_are_idempotent_and_conflicts_fail(self) -> None:
        with tempfile.TemporaryDirectory(prefix="batch-run-test-") as temporary:
            report = Path(temporary) / "batch-report.jsonl"
            event = _event(
                "BATCH-001", "batch-001", "a" * 40, "STARTED", 1, "batch-001-started",
                observed_at="2026-08-27T00:00:00+09:00",
            )
            _append_events(report, [event])
            _append_events(report, [event])
            self.assertEqual(1, len(report.read_text(encoding="utf-8").splitlines()))
            conflict = dict(event, token_count=0)
            with self.assertRaises(BatchRunError):
                _append_events(report, [conflict])

    def test_plan_projection_adds_structured_brief_without_changing_child_plan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="batch-projection-test-") as temporary:
            root = Path(temporary)
            child_plan = root / "child" / "production-plan.yaml"
            child_markdown = root / "child" / "production-plan.md"
            child_brief = root / "research" / "production-brief.yaml"
            child_plan.parent.mkdir()
            child_brief.parent.mkdir()
            child_plan.write_text(
                yaml.safe_dump({"readiness": {"startable": True}, "plan_id": "PL001"}, sort_keys=False),
                encoding="utf-8",
            )
            child_markdown.write_text("# plan\n", encoding="utf-8")
            child_brief.write_text(
                yaml.safe_dump({
                    "message": {"who_disagrees": "a designer"},
                    "concept": {"without_the_technique": "CEASES_TO_WORK", "precedents": [{"reference": "PA001"}]},
                }, sort_keys=False),
                encoding="utf-8",
            )
            before = child_plan.read_bytes()
            plan_hash, brief_hash = _prepare_plan_projection(
                child_plan, child_brief, root / "output/production-plan.yaml", root / "output/production-plan.md",
            )
            projection = yaml.safe_load((root / "output/production-plan.yaml").read_text(encoding="utf-8"))
            self.assertTrue(projection["readiness"]["startable"])
            self.assertEqual("CEASES_TO_WORK", projection["brief"]["concept"]["without_the_technique"])
            self.assertEqual(before, child_plan.read_bytes())
            self.assertEqual(64, len(plan_hash))
            self.assertEqual(64, len(brief_hash))
            self.assertEqual(b"# plan\n", (root / "output/production-plan.md").read_bytes())

    def test_profiled_batch_derives_output_root_and_passes_one_resolution(self) -> None:
        repository_root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory(prefix="batch-destinations-") as temporary:
            root = Path(temporary)
            profile = root / "profile.yaml"
            profile.write_text(yaml.safe_dump({
                "contract_version": "output-destinations/v1",
                "profile": "test",
                "destinations": {
                    "state_root": str(root / "state"),
                    "internal_output_root": str(root / "internal"),
                },
            }, sort_keys=False), encoding="utf-8")
            fake_result = {"status": "PASSED", "summary_path": root / "summary.json"}
            with patch("tools.batch_run.run_batch", return_value=fake_result) as run_mock:
                status = main([
                    "--manifest", str(repository_root / "config/repositories.yaml"),
                    "--workspace-root", str(root / "workspace"),
                    "--self-export", str(root / "self.json"),
                    "--art-history-export", str(root / "art.json"),
                    "--marketing-export", str(root / "marketing.json"),
                    "--destinations-file", str(profile),
                    "--run-id", "BATCH-001",
                    "--generated-at", "2026-08-27T00:00:00+09:00",
                    "--child-python", sys.executable,
                    "--limit", "1",
                ])
            self.assertEqual(0, status)
            kwargs = run_mock.call_args.kwargs
            self.assertEqual((root / "internal" / "batch" / "BATCH-001").resolve(), kwargs["output_root"])
            self.assertEqual((root / "state").resolve(), kwargs["state_root"])
            self.assertEqual("destination-resolution/v1", kwargs["destination_resolution"]["contract_version"])


if __name__ == "__main__":
    unittest.main()
