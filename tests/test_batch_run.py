from __future__ import annotations

from contextlib import redirect_stdout
import copy
import hashlib
import io
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
    _project_passed_batch,
    main,
    validate_batch_run,
)
from tests.test_canonical_plan_projection import write_fake_attestation_tool


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
                "prototype_status": "READY",
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
                "g7_prototype_output_ready": True,
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


class BatchAutomaticAttestationTests(unittest.TestCase):
    """The batch projection runs the same automatic attestation as tools/run.py first."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="batch-attest-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.code = self.root / "production-code"
        write_fake_attestation_tool(self.code)
        self.plan = self.root / "internal" / "batch" / "canonical-production" / "batch-001" / "attempt-1" / \
            "production" / "batch-001" / "03_plan" / "production-plan.md"
        self.plan.parent.mkdir(parents=True)
        self.plan.write_bytes(b"# Batch plan\n")
        self.summary = BatchRunContractTests()._summary()
        self.summary["projects"][0].update(plan=str(self.plan), production_code_root=str(self.code),
                                           production_source_commit="b" * 40)

    def resolution(self, public: bool = True) -> dict:
        destinations = {"state_root": {"path": str(self.root / "state")},
                        "internal_output_root": {"path": str(self.root / "internal")}}
        if public:
            destinations["public_projection_root"] = {"path": str(self.root / "public")}
        return {"contract_version": "destination-resolution/v1", "destinations": destinations}

    def project(self, summary: dict, public: bool = True):
        projected = []

        def fake_projection(source, **kwargs):
            projected.append(copy.deepcopy(source))
            return {"status": "APPLIED"}

        with patch("tools.batch_run.project_batch_automatic", side_effect=fake_projection):
            result = _project_passed_batch(
                summary, destination_resolution=self.resolution(public), state_root=self.root / "state",
                run_id="BATCH-001", generated_at="2026-08-27T00:00:00+09:00", child_python=sys.executable,
            )
        return result, projected

    def calls(self) -> list[list[str]]:
        log = self.code / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def test_batch_projection_attests_each_plan_and_projects_the_owner_locator(self) -> None:
        (projection, attestation), projected = self.project(self.summary)
        self.assertEqual({"status": "APPLIED"}, projection)
        self.assertEqual("PASSED", attestation["status"])
        self.assertEqual([{"project_id": "batch-001", "status": "ATTESTED"}], attestation["projects"])
        calls = self.calls()
        self.assertEqual(1, len(calls))
        self.assertIn("--automatic-plan", calls[0])
        self.assertEqual("b" * 40, calls[0][calls[0].index("--producer-commit") + 1])
        item = projected[0]["projects"][0]
        written = self.plan.with_name("public-plan-attestation.json")
        self.assertEqual(str(written), item["public_plan_attestation"])
        self.assertEqual(hashlib.sha256(written.read_bytes()).hexdigest(), item["public_plan_attestation_sha256"])
        self.assertEqual([], validate_batch_run(projected[0]))

    def test_rejected_batch_attestation_blocks_before_projection(self) -> None:
        (self.code / "reject").write_text("PUBLIC_URL_BLOCKED\n", encoding="utf-8")
        (projection, attestation), projected = self.project(self.summary)
        self.assertIsNone(projection)
        self.assertEqual([], projected)
        self.assertEqual("BLOCKED", attestation["status"])
        self.assertEqual("PRODUCTION_AUTOMATIC_ATTESTATION_FAILED", attestation["stop_reason"])
        self.assertEqual({"status": "REJECTED", "reason": "PUBLIC_URL_BLOCKED"}, attestation["projects"][0]["finding"])

    def test_resumed_batch_with_a_changed_plan_reattests(self) -> None:
        self.project(copy.deepcopy(self.summary))
        self.plan.write_bytes(b"# Changed batch plan\n")
        (projection, attestation), _ = self.project(copy.deepcopy(self.summary))
        self.assertEqual({"status": "APPLIED"}, projection)
        entry = attestation["projects"][0]
        self.assertEqual("REATTESTED", entry["status"])
        self.assertEqual("PLAN_BYTES_CHANGED", entry["retired"]["reason"])
        self.assertEqual(self.root / "state" / "BATCH-001" / "superseded-attestations" / "batch-001",
                         Path(entry["retired"]["path"]).parent)

    def test_internal_only_batch_projects_nothing_and_needs_no_attestation(self) -> None:
        (projection, attestation), projected = self.project(self.summary, public=False)
        self.assertIsNone(projection)
        self.assertIsNone(attestation)
        self.assertEqual([], projected)
        self.assertEqual([], self.calls())

    def test_cli_exits_2_with_the_stop_reason_when_attestation_blocks(self) -> None:
        repository_root = Path(__file__).parents[1]
        blocked = {"status": "BLOCKED", "stop_reason": "PRODUCTION_AUTOMATIC_ATTESTATION_FAILED",
                   "projects": [{"project_id": "batch-001", "status": "UNAVAILABLE"}]}
        fake_result = {"status": "PASSED", "summary_path": self.root / "summary.json",
                       "public_projection": None, "automatic_plan_attestation": blocked}
        stdout = io.StringIO()
        with patch("tools.batch_run.run_batch", return_value=fake_result), redirect_stdout(stdout):
            status = main([
                "--manifest", str(repository_root / "config/repositories.yaml"),
                "--workspace-root", str(self.root / "workspace"),
                "--self-export", str(self.root / "self.json"),
                "--art-history-export", str(self.root / "art.json"),
                "--marketing-export", str(self.root / "marketing.json"),
                "--output-root", str(self.root / "out"),
                "--state-root", str(self.root / "state"),
                "--run-id", "BATCH-001",
                "--generated-at", "2026-08-27T00:00:00+09:00",
                "--child-python", sys.executable,
                "--limit", "1",
            ])
        self.assertEqual(2, status)
        output = json.loads(stdout.getvalue())
        self.assertEqual("PRODUCTION_AUTOMATIC_ATTESTATION_FAILED", output["stop_reason"])
        self.assertEqual(blocked, output["automatic_plan_attestation"])


if __name__ == "__main__":
    unittest.main()
