from __future__ import annotations

from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from tools import public_projection
from tools.batch_run import (
    SOURCE_REPOSITORIES,
    BatchRunError,
    _append_events,
    _event,
    _prepare_plan_projection,
    _project_passed_batch,
    main,
    run_batch,
    validate_batch_run,
)
from tools.delivery_completion import completion
from tools.output_destinations import resolve_destinations
from tests.test_canonical_plan_projection import write_fake_attestation_tool
from tests.test_plan_view import PLAN

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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

    def test_a_blocked_summary_must_meet_the_passed_counts_and_acceptance(self) -> None:
        blocked = self._summary()
        blocked.update(status="BLOCKED", stop_reason="PRODUCTION_AUTOMATIC_ATTESTATION_FAILED",
                       automatic_plan_attestation={"status": "BLOCKED", "projects": []})
        self.assertEqual([], validate_batch_run(blocked))
        failing = copy.deepcopy(blocked)
        failing["acceptance"]["g7_prototype_output_ready"] = False
        self.assertIn("BLOCKED run must satisfy every acceptance boolean", " ".join(validate_batch_run(failing)))
        short = copy.deepcopy(blocked)
        short.update(completed_count=0, failed_count=1)
        self.assertIn("BLOCKED run counts are inconsistent", " ".join(validate_batch_run(short)))

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



def _committed_production(code: Path, revision: str) -> str:
    """A clean, committed fake Production checkout; the owner check pins HEAD and cleanliness."""
    write_fake_attestation_tool(code)
    (code / ".gitignore").write_text("calls.jsonl\n__pycache__/\n", encoding="utf-8")
    (code / "REVISION").write_text(revision + "\n", encoding="utf-8")
    if not (code / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main", str(code)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(code), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(code), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-q", "-m", revision], check=True, capture_output=True)
    return subprocess.check_output(["git", "-C", str(code), "rev-parse", "HEAD"], text=True).strip()


class BatchResumeProjectionTests(unittest.TestCase):
    """The real run_batch, attestation and canonical projection; only batch production is faked."""

    RUN_ID = "BATCH-RESUME-001"

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="batch-resume-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.code = self.root / "production-code"
        self.head = _committed_production(self.code, "one")
        self.target = self.root / "public-target"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.target)], check=True, capture_output=True)
        public_projection.init_target(self.target, apply=True)
        subprocess.run(["git", "-C", str(self.target), "add", "public-project.yaml", "README.md", "plans", "works"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.target), "-c", "user.name=fixture", "-c",
                        "user.email=fixture@example.invalid", "commit", "-q", "-m", "scaffold"],
                       check=True, capture_output=True)
        profile = self.root / "destinations.yaml"
        profile.write_text(yaml.safe_dump({
            "contract_version": "output-destinations/v1", "profile": "batch-resume-test",
            "destinations": {"state_root": str(self.root / "state"), "internal_output_root": str(self.root / "internal"),
                             "public_projection_root": str(self.target)},
        }, sort_keys=False), encoding="utf-8")
        self.resolution = resolve_destinations(profile, repository_root=REPOSITORY_ROOT, run_id=self.RUN_ID)
        self.output_root = self.root / "internal" / "batch" / self.RUN_ID
        self.plan = (self.output_root / "canonical-production" / "batch-001" / "attempt-1" / "production" /
                     "batch-001" / "03_plan" / "production-plan.md")
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.manifest = yaml.safe_load((REPOSITORY_ROOT / "config/repositories.yaml").read_text(encoding="utf-8"))

    def run_batch(self, **patches):
        return run_batch(
            self.manifest, self.workspace, self_export=self.root / "self.json",
            art_history_export=self.root / "art.json", marketing_export=self.root / "marketing.json",
            output_root=self.output_root, state_root=self.root / "state", run_id=self.RUN_ID,
            generated_at="2026-10-30T00:00:00+09:00", child_python=sys.executable, selection_limit=1,
            destination_resolution=self.resolution,
        )

    def summary_path(self) -> Path:
        return self.root / "state" / self.RUN_ID / "batch-run.json"

    def calls(self) -> list[list[str]]:
        log = self.code / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def public_plan(self) -> bytes:
        record, = yaml.safe_load((self.target / "plans/index.yaml").read_text(encoding="utf-8"))["records"]
        return (self.target / record["path"] / "plan.md").read_bytes()

    def fake_project(self, **kwargs) -> dict:
        """One PASSED batch project with its canonical plan; no child exchange."""
        from tools.canonical_plan_projection import source_fields
        self.plan.parent.mkdir(parents=True, exist_ok=True)
        self.plan.write_text(PLAN, encoding="utf-8")
        report = self.output_root / "production" / "batch-001" / "03_plan" / "production-plan.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(PLAN, encoding="utf-8")
        return {**source_fields(self.plan, self.code), "project_id": "batch-001",
                "candidate_id": "candidate:" + "1" * 16, "status": "PASSED", "prototype_status": "READY",
                "research_locator": f"run://{self.RUN_ID}/research/projects/batch-001",
                "production_locator": f"run://{self.RUN_ID}/production/batch-001",
                "production_plan_sha256": "a" * 64, "production_repository": "agentic-art-production",
                "production_source_commit": self.head,
                "production_plan_markdown_sha256": hashlib.sha256(self.plan.read_bytes()).hexdigest(),
                "brief_sha256": "b" * 64, "decision_log_sha256": "c" * 64, "events": []}

    def fresh_batch(self):
        """run_batch's fresh path with selection and child production faked out."""
        records = [{"source": {"repository": repository, "commit": str(index) * 40}}
                   for index, repository in enumerate(sorted(SOURCE_REPOSITORIES.values()), start=1)]
        checks = {key: True for key in ("g1_production_plan_count", "g2_startable", "g3_structured_brief",
                                        "g4_no_human_authority", "g5_agent_recommended_decisions",
                                        "g6_append_only_report", "g7_prototype_output_ready",
                                        "no_remote_operations", "no_child_mutations", "no_raw_data")}
        detail = {"report": {"event_count": 1, "counts": {"完了": 1, "失敗": 0, "再試行": 0},
                             "duration": {"total_seconds": 1.0}, "tokens": {"total": None}}}
        candidate = {"candidate_id": "candidate:" + "1" * 16}
        with patch("tools.batch_run.workspace_candidate", side_effect=lambda manifest, root: (manifest, [])), \
                patch("tools.batch_run._load_export", return_value=[]), \
                patch("tools.batch_run.build_signal_bundle", return_value={"records": records}), \
                patch("tools.batch_run.build_candidate_space", return_value={}), \
                patch("tools.batch_run.build_gate_report", return_value={}), \
                patch("tools.batch_run.build_selection",
                      return_value={"selected_candidates": [candidate], "selected_count": 1}), \
                patch("tools.batch_run.build_self_diversity_report",
                      return_value={"status": "INSUFFICIENT_SELF_DIVERSITY"}), \
                patch("tools.batch_run._signal_tuple", side_effect=lambda item: (("candidate", item["candidate_id"]),)), \
                patch("tools.batch_run._run_project", side_effect=self.fake_project), \
                patch("tools.batch_run._acceptance_checks", return_value=(checks, detail)):
            return self.run_batch()

    def write_attested_summary(self) -> dict:
        """A PASSED summary as the fresh path writes it: attested, not yet projected."""
        from tools.batch_run import _attest_batch_projects, _refresh_plan_authority
        summary = BatchRunContractTests()._summary()
        summary["run_id"] = self.RUN_ID
        project = self.fake_project()
        project.pop("events")
        summary["projects"] = [project]
        summary["destination_resolution"] = dict(self.resolution)
        summary["output_root_locator"] = f"batch/{self.RUN_ID}"
        attested = _attest_batch_projects(summary["projects"], child_python=sys.executable,
                                          generated_at="2026-10-29T00:00:00+09:00",
                                          superseded_root=self.root / "state" / self.RUN_ID / "superseded",
                                          public_projection_root=self.target)
        self.assertEqual("PASSED", attested["status"])
        _refresh_plan_authority(summary, self.resolution)
        self.assertEqual([], validate_batch_run(summary))
        self.summary_path().parent.mkdir(parents=True)
        self.summary_path().write_text(json.dumps(summary), encoding="utf-8")
        return summary

    def test_resume_after_the_plan_changed_reattests_and_projects_the_new_bytes(self) -> None:
        """Through run_batch's resume path with the real projection, not a mocked one."""
        written = self.write_attested_summary()
        changed = PLAN.replace("# 制作プラン", "# 制作プラン（改訂）", 1).encode("utf-8")
        self.plan.write_bytes(changed)

        result = self.run_batch()

        self.assertEqual("ALREADY_COMPLETED", result["status"])
        attestation = result["automatic_plan_attestation"]
        self.assertEqual("PASSED", attestation["status"])
        self.assertEqual("REATTESTED", attestation["projects"][0]["status"])
        self.assertEqual("PLAN_BYTES_CHANGED", attestation["projects"][0]["retired"]["reason"])
        self.assertEqual("APPLIED", result["public_projection"]["status"], result["public_projection"])
        self.assertEqual(changed, self.public_plan())
        # The PASSED summary on disk now carries the attested hash and authority.
        saved = json.loads(self.summary_path().read_text(encoding="utf-8"))
        self.assertEqual(saved, result["summary"])
        self.assertEqual(hashlib.sha256(changed).hexdigest(), saved["projects"][0]["production_plan_markdown_sha256"])
        self.assertNotEqual(written["automatic_plan_authority"], saved["automatic_plan_authority"])
        self.assertEqual([], validate_batch_run(saved))
        self.assertEqual([], [path.name for path in self.summary_path().parent.iterdir() if path.name.endswith(".tmp")])
        # A second resume is idempotent: the attestation is reused and nothing is written.
        before = self.summary_path().read_bytes()
        again = self.run_batch()
        self.assertEqual("ALREADY_ATTESTED", again["automatic_plan_attestation"]["projects"][0]["status"])
        self.assertEqual("ALREADY_PROJECTED", again["public_projection"]["status"])
        self.assertEqual(before, self.summary_path().read_bytes())

    def prepare_from_summary(self) -> tuple[int, dict]:
        """`public_projection.py prepare --batch-summary` on the summary file on disk."""
        profile = self.root / "destinations.yaml"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = public_projection.main([
                "prepare", "--batch-summary", str(self.summary_path()), "--projection-id", self.RUN_ID,
                "--destinations-file", str(profile),
            ])
        return status, json.loads(stdout.getvalue())

    def test_a_later_projection_from_the_resumed_summary_file_verifies_the_attested_plan(self) -> None:
        """The rewritten batch-run.json is what a later batch-summary projection reads."""
        self.write_attested_summary()
        changed = PLAN.replace("# 制作プラン", "# 制作プラン（改訂）", 1).encode("utf-8")
        report = self.output_root / "production" / "batch-001" / "03_plan" / "production-plan.md"
        for path in (self.plan, report):
            path.write_bytes(changed)
        # The stale summary names the old plan hash, so it cannot be projected.
        stale_status, _stale = self.prepare_from_summary()
        self.assertEqual(2, stale_status)

        result = self.run_batch()
        self.assertEqual("APPLIED", result["public_projection"]["status"], result["public_projection"])

        status, output = self.prepare_from_summary()
        self.assertEqual(0, status, output)
        self.assertEqual(1, output["record_count"])

    def test_a_resumed_blocked_summary_that_breaks_the_counts_is_not_attested(self) -> None:
        (self.code / "reject").write_text("PUBLIC_URL_BLOCKED\n", encoding="utf-8")
        self.fresh_batch()
        (self.code / "reject").unlink()
        calls = len(self.calls())
        saved = json.loads(self.summary_path().read_text(encoding="utf-8"))
        saved["acceptance"]["g7_prototype_output_ready"] = False
        self.summary_path().write_text(json.dumps(saved), encoding="utf-8")
        with self.assertRaises(BatchRunError):
            self.run_batch()
        self.assertEqual(calls, len(self.calls()))

    def test_fresh_batch_with_a_rejected_attestation_is_recorded_blocked_and_resumes(self) -> None:
        (self.code / "reject").write_text("PUBLIC_URL_BLOCKED\n", encoding="utf-8")
        result = self.fresh_batch()

        self.assertEqual("BLOCKED", result["status"])
        self.assertIsNone(result["public_projection"])
        saved = json.loads(self.summary_path().read_text(encoding="utf-8"))
        self.assertEqual("BLOCKED", saved["status"])
        self.assertEqual("PRODUCTION_AUTOMATIC_ATTESTATION_FAILED", saved["stop_reason"])
        self.assertEqual({"status": "REJECTED", "reason": "PUBLIC_URL_BLOCKED"},
                         saved["automatic_plan_attestation"]["projects"][0]["finding"])
        self.assertNotIn("automatic_plan_authority", saved)
        self.assertEqual([], validate_batch_run(saved))
        # delivery_completion describes the BLOCKED summary, not the PASSED one it was.
        self.assertEqual(completion(saved, saved["delivery_contract"]), saved["delivery_completion"])
        self.assertIn("PRODUCTION_PLAN", saved["delivery_completion"]["missing"])

        # A resume that is still rejected keeps the honest BLOCKED summary.
        still = self.run_batch()
        self.assertEqual("BLOCKED", still["automatic_plan_attestation"]["status"])
        blocked = json.loads(self.summary_path().read_text(encoding="utf-8"))
        self.assertEqual("BLOCKED", blocked["status"])
        self.assertIn("PRODUCTION_PLAN", blocked["delivery_completion"]["missing"])

        (self.code / "reject").unlink()
        resumed = self.run_batch()
        self.assertEqual("PASSED", resumed["automatic_plan_attestation"]["status"])
        self.assertEqual("APPLIED", resumed["public_projection"]["status"], resumed["public_projection"])
        saved = json.loads(self.summary_path().read_text(encoding="utf-8"))
        self.assertEqual("PASSED", saved["status"])
        self.assertNotIn("stop_reason", saved)
        self.assertEqual("tools/batch_run.py", saved["automatic_plan_authority"]["producer"])
        self.assertEqual([], validate_batch_run(saved))
        self.assertEqual(completion(saved, saved["delivery_contract"]), saved["delivery_completion"])
        self.assertNotIn("PRODUCTION_PLAN", saved["delivery_completion"]["missing"])
        self.assertEqual(PLAN.encode("utf-8"), self.public_plan())

    def test_an_unexpected_os_error_in_attestation_leaves_a_resumable_blocked_summary(self) -> None:
        with patch("tools.canonical_plan_projection.ensure_automatic_attestation", side_effect=OSError("disk")):
            result = self.fresh_batch()

        self.assertEqual("BLOCKED", result["status"])
        saved = json.loads(self.summary_path().read_text(encoding="utf-8"))
        self.assertEqual("BLOCKED", saved["status"])
        finding = saved["automatic_plan_attestation"]["projects"][0]["finding"]
        self.assertEqual("UNAVAILABLE", finding["status"])
        self.assertTrue(finding["reason"].startswith("OSError: "))
        self.assertNotIn("disk", json.dumps(saved))
        self.assertEqual([], [path.name for path in self.summary_path().parent.iterdir() if path.name.endswith(".tmp")])

        resumed = self.run_batch()  # no "partial batch state exists"
        self.assertEqual("APPLIED", resumed["public_projection"]["status"], resumed["public_projection"])
        self.assertEqual("PASSED", json.loads(self.summary_path().read_text(encoding="utf-8"))["status"])

    def test_fresh_batch_that_attests_projects_and_records_passed(self) -> None:
        result = self.fresh_batch()
        self.assertEqual("PASSED", result["status"])
        self.assertEqual("APPLIED", result["public_projection"]["status"], result["public_projection"])
        saved = json.loads(self.summary_path().read_text(encoding="utf-8"))
        self.assertEqual("PASSED", saved["status"])
        self.assertNotIn("stop_reason", saved)
        self.assertEqual(1, sum("--automatic-plan" in call for call in self.calls()))


if __name__ == "__main__":
    unittest.main()
