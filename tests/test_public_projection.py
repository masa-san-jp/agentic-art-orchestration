from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import yaml

from tools import public_projection as projection
from tools.output_destinations import resolve_destinations
from tools.repo_local_destinations import resolve_project_root
from tools.security import PUBLIC_PROJECTION_FINDING_CODES, scan_public_projection


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/public-projection"


def synthetic_owner_boundary(item, internal):
    """Transaction-only test double; never Production or live acceptance evidence."""
    slug = item.get("project_slug", item.get("project_id"))
    path = Path(item["plan"]) if "plan" in item else next(internal.glob("batch/*/production/" + slug + "/03_plan/production-plan.md"))
    body = path.read_bytes(); attestation = b'{"synthetic_boundary_only":true}\n'
    return {"identity": "production/" + slug + "#PL001", "revision": item.get("plan_revision", 1),
        "body_hash": hashlib.sha256(body).hexdigest(), "attestation_hash": hashlib.sha256(attestation).hexdigest(),
        "production_commit": item["production_source_commit"], "production_state": "PLANNING", "assets": [],
        "files": {"plan.md": body, "public-plan-attestation.json": attestation}}


class PublicProjectionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = yaml.safe_load((FIXTURE_ROOT / "layout.yaml").read_text(encoding="utf-8"))
        self.request = yaml.safe_load((FIXTURE_ROOT / "request.yaml").read_text(encoding="utf-8"))
        self.approval = yaml.safe_load((FIXTURE_ROOT / "approval.yaml").read_text(encoding="utf-8"))
        self.result = json.loads((FIXTURE_ROOT / "result.json").read_text(encoding="utf-8"))

    def test_closed_schemas_and_synthetic_fixtures_validate(self) -> None:
        expected = {
            "public-project-layout/v1": projection.LAYOUT_SCHEMA_PATH,
            "public-projection-request/v1": projection.REQUEST_SCHEMA_PATH,
            "public-projection-approval/v1": projection.APPROVAL_SCHEMA_PATH,
            "public-projection-result/v1": projection.RESULT_SCHEMA_PATH,
        }
        for contract_version, path in expected.items():
            with self.subTest(contract_version=contract_version):
                schema = projection.load_json(path)
                self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(contract_version, schema["properties"]["contract_version"]["const"])
        self.assertEqual([], projection.validate_layout(self.layout))
        self.assertEqual([], projection.validate_request(self.request))
        self.assertEqual([], projection.validate_approval(self.approval))
        self.assertEqual([], projection.validate_result(self.result))
        expected_hash = projection.request_sha256(self.request)
        self.assertEqual(expected_hash, self.approval["request_sha256"])
        self.assertEqual(expected_hash, self.result["request_sha256"])
        self.assertEqual("READY_FOR_DRY_RUN", projection.projection_policy_status(self.request))

    def test_record_hash_is_canonical_and_drift_is_rejected(self) -> None:
        record = self.request["records"][0]
        files = record["files"]
        self.assertEqual(record["source"]["sha256"], projection.record_file_sha256(files))
        changed = copy.deepcopy(self.request)
        changed["records"][0]["files"][1]["sha256"] = "4" * 64
        errors = projection.validate_request(changed)
        self.assertTrue(any("source.sha256" in error for error in errors))
        self.assertEqual("84ce220804f29e460c2915800dad3534116ba0ba0a1197e672e9604f6b3edbc4", record["source"]["sha256"])

    def test_unknown_clearance_is_blocked_without_becoming_public(self) -> None:
        draft = copy.deepcopy(self.request)
        draft["records"][0]["publication"]["visibility"] = "unknown"
        draft["records"][0]["publication"]["rights_status"] = "unknown"
        self.assertEqual([], projection.validate_request(draft))
        findings = projection.request_policy_findings(draft)
        self.assertEqual("BLOCKED_POLICY", projection.projection_policy_status(draft))
        self.assertGreaterEqual(len(findings), 2)
        self.assertTrue(all(item["code"] == "UNKNOWN_CLEARANCE" for item in findings))

        blocked = copy.deepcopy(self.result)
        blocked["status"] = "BLOCKED_POLICY"
        blocked["findings"] = findings[:1]
        self.assertEqual([], projection.validate_result(blocked))
        self.assertEqual(0, blocked["target"]["mutation_count"])
        self.assertEqual([], blocked["changed_paths"])

    def test_public_security_scan_is_sanitized_and_vocabulary_is_closed(self) -> None:
        findings = scan_public_projection(
            {
                "PRIVATE_RAW": "do not copy",
                "body": "token: ghp_test_secret_value",
                "source_locator": "/Users/example/private.gdoc",
                "provider_url": "https://drive.google.com/drive/folders/internal",
                "direct_identifier": "person@example.test",
            },
            "fixture:public",
        )
        codes = {item["code"] for item in findings}
        self.assertTrue({"FORBIDDEN_CONTENT", "CREDENTIAL", "ABSOLUTE_PATH", "FORBIDDEN_ARTIFACT", "PRIVATE_URL", "INTERNAL_REFERENCE"}.issubset(codes))
        self.assertTrue(codes.issubset(PUBLIC_PROJECTION_FINDING_CODES))
        rendered = json.dumps(findings, ensure_ascii=False, sort_keys=True)
        for forbidden in ("do not copy", "ghp_test_secret_value", "/Users/example", "person@example.test"):
            self.assertNotIn(forbidden, rendered)

    def test_result_rejects_target_mutation_for_blocked_status(self) -> None:
        changed = copy.deepcopy(self.result)
        changed["status"] = "BLOCKED_CONFLICT"
        changed["target"]["mutation_count"] = 1
        changed["changed_paths"] = ["plans/P0001-example-plan/plan.md"]
        errors = projection.validate_result(changed)
        self.assertTrue(any("target mutation" in error for error in errors))

        remote = copy.deepcopy(self.result)
        remote["remote_operations"] = [{"operation": "PUSH"}]
        errors = projection.validate_result(remote)
        self.assertTrue(any("remote_operations" in error for error in errors))

    def test_approval_window_and_cli_are_deterministic_and_read_only(self) -> None:
        invalid = copy.deepcopy(self.approval)
        invalid["expires_at"] = "2026-09-03T00:00:00Z"
        errors = projection.validate_approval(invalid)
        self.assertTrue(any("expires_at" in error for error in errors))

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                0,
                projection.main(["validate", "--layout", str(FIXTURE_ROOT / "layout.yaml"), "--request", str(FIXTURE_ROOT / "request.yaml")]),
            )
        report = json.loads(output.getvalue())
        self.assertEqual("PASSED", report["status"])
        self.assertEqual("READY_FOR_DRY_RUN", report["policy_status"])

    def _profile_resolution(self, root: Path, run_id: str, *, public: bool = False) -> dict:
        destinations = {
            "state_root": str(root / "state"),
            "internal_output_root": str(root / "internal"),
        }
        if public:
            destinations["public_projection_root"] = str(root / "public-target")
        profile = root / "destinations.yaml"
        profile.write_text(
            yaml.safe_dump({
                "contract_version": "output-destinations/v1",
                "profile": "prepare-test",
                "destinations": destinations,
            }, sort_keys=False),
            encoding="utf-8",
        )
        return resolve_destinations(profile, repository_root=ROOT, run_id=run_id)

    def _git(self, root: Path, *arguments: str) -> str:
        completed = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, check=True)
        return completed.stdout.strip()

    def _new_target(self, root: Path) -> Path:
        target = root / "public-target"
        subprocess.run(["git", "init", "-q", "-b", "main", str(target)], check=True, capture_output=True)
        self._git(target, "config", "user.name", "Public Projection Fixture")
        self._git(target, "config", "user.email", "fixture@example.invalid")
        return target

    def _prepared_public_request(self, root: Path, projection_id: str = "PUBLIC-PLAN-001") -> Path:
        run_id = "RUN-PROJECT-001"
        resolution = self._profile_resolution(root, run_id)
        source = root / "internal" / "production" / "example-plan" / "03_plan" / "production-plan.md"
        source.parent.mkdir(parents=True)
        content = b"# Example public plan\n\nOnly public-ready candidate content.\n"
        source.write_bytes(content)
        report = {
            "run_id": run_id,
            "status": "PLAN_READY",
            "generated_at": "2026-09-04T00:00:00Z",
            "project_slug": "example-plan",
            "project_title": "Example public plan",
            "plan": str(source),
            "production_plan_sha256": hashlib.sha256(content).hexdigest(),
            "production_repository": "agentic-art-production",
            "production_source_commit": "d" * 40,
            "destination_resolution": resolution,
        }
        prepared = projection.prepare_run_report(report, internal_output_root=root / "internal", projection_id=projection_id)
        request_path = root / "internal" / prepared["request_locator"]
        request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
        request["records"][0]["publication"] = {
            "visibility": "public",
            "rights_status": "cleared",
            "consent_status": "cleared",
            "attribution": [],
        }
        for file in request["records"][0]["files"]:
            file["rights_status"] = "cleared"
        request_path.write_bytes(projection._request_yaml_bytes(request))
        return request_path

    def _approval_for(self, root: Path, request_path: Path, *, request_hash: str | None = None) -> Path:
        request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
        approval = copy.deepcopy(self.approval)
        approval["request_sha256"] = request_hash or projection.request_sha256(request)
        approval_path = root / f"{request['projection_id']}-approval.yaml"
        approval_path.write_bytes(projection._request_yaml_bytes(approval))
        return approval_path

    def _automatic_report(self, root: Path, run_id: str = "RUN-AUTO-001") -> dict:
        resolution = self._profile_resolution(root, run_id, public=True)
        source = root / "internal" / "production" / "automatic-plan" / "03_plan" / "production-plan.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        content = b"# Automatically public plan\n\nThis plan is emitted by the completed orchestration flow.\n"
        source.write_bytes(content)
        report = {
            "run_id": run_id,
            "status": "PLAN_READY",
            "generated_at": "2026-09-04T00:00:00Z",
            "project_slug": "automatic-plan",
            "project_title": "Automatically public plan",
            "plan": str(source),
            "production_plan_sha256": hashlib.sha256(content).hexdigest(),
            "production_repository": "agentic-art-production",
            "production_source_commit": "a" * 40,
            "destination_resolution": resolution,
        }
        report["automatic_plan_authority"] = projection.build_automatic_plan_authority(
            producer="tools/run.py",
            source_status="PLAN_READY",
            source_id=run_id,
            source_sha256=report["production_plan_sha256"],
            destination_resolution=resolution,
        )
        return report

    def _automatic_batch_summary(self, root: Path, count: int = 100, run_id: str = "BATCH-AUTO-001") -> dict:
        resolution = self._profile_resolution(root, run_id, public=True)
        output_root = root / "internal" / "batch" / run_id
        commit = "b" * 40
        plans: list[dict[str, object]] = []
        for index in range(1, count + 1):
            project_id = f"batch-plan-{index:03d}"
            source = output_root / "production" / project_id / "03_plan" / "production-plan.md"
            source.parent.mkdir(parents=True, exist_ok=True)
            content = f"# Batch plan {index:03d}\n\nPlan emitted by the completed batch.\n".encode("utf-8")
            source.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            plans.append({
                "project_id": project_id,
                "candidate_id": f"candidate:{index:016x}",
                "status": "PASSED",
                "research_locator": f"run://{run_id}/research/projects/{project_id}",
                "production_locator": f"run://{run_id}/production/{project_id}",
                "production_plan_sha256": digest,
                "production_repository": "agentic-art-production",
                "production_source_commit": commit,
                "production_plan_markdown_sha256": digest,
                "brief_sha256": "c" * 64,
                "decision_log_sha256": "d" * 64,
            })
        summary = {
            "contract_version": "batch-run/v1",
            "run_id": run_id,
            "generated_at": "2026-09-04T00:00:00Z",
            "network": "DISABLED",
            "status": "PASSED",
            "requested_count": count,
            "completed_count": count,
            "failed_count": 0,
            "source_repositories": [
                {"repository": "art-history", "commit": commit, "record_count": 1},
                {"repository": "marketing-trends", "commit": "c" * 40, "record_count": 1},
                {"repository": "self-model", "commit": "d" * 40, "record_count": 1},
            ],
            "selection": {
                "candidate_space_hash": "a" * 64,
                "gate_report_hash": "b" * 64,
                "selection_hash": "c" * 64,
                "selected_count": count,
                "unique_signal_tuple_count": count,
                "self_diversity_status": "PASS",
                "source_commits": [commit, "c" * 40, "d" * 40],
            },
            "projects": plans,
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
                "locator": f"run://{run_id}/batch-report.jsonl",
                "sha256": "e" * 64,
                "event_count": count,
                "completed_count": count,
                "failed_count": 0,
                "retry_count": 0,
                "duration_seconds": 1.0,
                "token_count": None,
            },
            "destination_resolution": resolution,
            "output_root_locator": f"batch/{run_id}",
            "remote_operations": [],
            "child_mutations": [],
        }
        authority_plans = [
            {
                "project_id": item["project_id"],
                "production_plan_markdown_sha256": item["production_plan_markdown_sha256"],
            }
            for item in plans
        ]
        summary["automatic_plan_authority"] = projection.build_automatic_plan_authority(
            producer="tools/batch_run.py",
            source_status="PASSED",
            source_id=run_id,
            source_sha256=projection.sha256_hex({"projects": sorted(authority_plans, key=lambda item: item["project_id"])}),
            destination_resolution=resolution,
        )
        return summary

    @patch("tools.canonical_plan_projection._owner_bundle", synthetic_owner_boundary)
    def test_automatic_plan_projection_applies_without_public_share_approval_and_replays_idempotently(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-plan-automatic-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            report = self._automatic_report(root)
            before_head = self._git(target, "rev-parse", "HEAD")

            applied = projection.project_plan_automatic(
                report,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
            )

            self.assertEqual("APPLIED", applied["status"])
            self.assertEqual("AUTOMATIC_PLAN", applied["projection_mode"])
            self.assertEqual("NOT_REQUIRED", applied["human_gate"])
            self.assertEqual(["P0001"], applied["public_ids"])
            self.assertEqual(before_head, self._git(target, "rev-parse", "HEAD"))
            self.assertTrue((target / "plans/P0001-automatic-plan/README.md").is_file())
            self.assertTrue((target / "plans/P0001-automatic-plan/plan.md").is_file())
            self.assertTrue((target / "plans/P0001-automatic-plan/metadata.yaml").is_file())
            metadata = yaml.safe_load((target / "plans/P0001-automatic-plan/metadata.yaml").read_text(encoding="utf-8"))
            self.assertEqual("public", metadata["visibility"])
            self.assertEqual("RUN-AUTO-001", metadata["source_run_id"])
            self.assertNotIn(str(root), json.dumps(metadata, ensure_ascii=False))

            self.assertEqual("canonical-plan-projection/v2", metadata["projection_contract"])
            self.assertTrue((target / "plans/P0001-automatic-plan/public-plan-attestation.json").is_file())
            evidence = json.loads((root / "state" / "RUN-AUTO-001" / "public-projection-result.json").read_text(encoding="utf-8"))
            self.assertEqual([], projection.validate_result(evidence))
            self.assertEqual("AUTOMATIC_PLAN", evidence["projection_mode"])
            self.assertIsNone(evidence["approval_sha256"])

            replay = projection.project_plan_automatic(
                report,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
            )
            self.assertEqual("ALREADY_PROJECTED", replay["status"])
            self.assertEqual([], replay["changed_paths"])
            self.assertEqual("NOT_REQUIRED", replay["human_gate"])

    @patch("tools.canonical_plan_projection._owner_bundle", synthetic_owner_boundary)
    def test_automatic_plan_projection_updates_opt_in_root_catalog(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-plan-root-catalog-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            (target / "README.md").write_text(
                "# Public project\n\n## Published plans\n\n"
                "<!-- agentic-art:catalog:start -->\n"
                "<!-- agentic-art:catalog:end -->\n",
                encoding="utf-8",
            )
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold root catalog")
            report = self._automatic_report(root, "RUN-AUTO-ROOT-001")

            result = projection.project_plan_automatic(
                report,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
            )

            self.assertEqual("APPLIED", result["status"])
            self.assertIn("README.md", result["changed_paths"])
            root_readme = (target / "README.md").read_text(encoding="utf-8")
            self.assertIn("plans/P0001-automatic-plan/README.md", root_readme)
            self.assertNotIn("<!-- agentic-art:catalog:start -->\n<!-- agentic-art:catalog:end -->", root_readme)

    def test_automatic_plan_projection_requires_configured_public_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-plan-config-") as temporary:
            root = Path(temporary)
            report = self._automatic_report(root, "RUN-AUTO-CONFIG-001")
            report["destination_resolution"] = self._profile_resolution(root, "RUN-AUTO-CONFIG-001")
            report["automatic_plan_authority"] = projection.build_automatic_plan_authority(
                producer="tools/run.py",
                source_status="PLAN_READY",
                source_id=report["run_id"],
                source_sha256=report["production_plan_sha256"],
                destination_resolution=report["destination_resolution"],
            )
            result = projection.project_plan_automatic(
                report,
                internal_output_root=root / "internal",
                public_projection_root=None,
                state_root=root / "state",
            )
            self.assertEqual("BLOCKED_CONFIGURATION", result["status"])
            self.assertEqual("AUTOMATIC_PLAN", result["projection_mode"])
            self.assertEqual("NOT_REQUIRED", result["human_gate"])
            self.assertEqual([], result["changed_paths"])
            self.assertIn("CONFIGURATION_MISSING", set(result["finding_codes"]))
            self.assertIsNone(result["request_locator"])
            evidence = json.loads((root / "state" / "RUN-AUTO-CONFIG-001" / "public-projection-result.json").read_text(encoding="utf-8"))
            self.assertEqual([], projection.validate_result(evidence))

    def test_automatic_authority_rejects_a_work_record(self) -> None:
        request = copy.deepcopy(self.request)
        request["projection_id"] = "RUN-AUTO-AUTHORITY-001"
        request["records"][0]["source"]["run_id"] = request["projection_id"]
        findings = projection._automatic_request_guard(request, projection_id=request["projection_id"], expected_record_count=1)
        self.assertEqual([], findings)
        request["records"][0]["record_kind"] = "work"
        findings = projection._automatic_request_guard(request, projection_id=request["projection_id"], expected_record_count=1)
        self.assertIn("AUTHORITY_INVALID", {item["code"] for item in findings})

    def test_automatic_projection_rejects_a_handwritten_source_without_authority(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-plan-authority-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            report = self._automatic_report(root, "RUN-AUTO-AUTHORITY-002")
            del report["automatic_plan_authority"]
            before = projection._tree_fingerprint(target)

            with self.assertRaises(projection.PreparationError) as raised:
                projection.project_plan_automatic(
                    report,
                    internal_output_root=root / "internal",
                    public_projection_root=target,
                    state_root=root / "state",
                )

            self.assertEqual("AUTHORITY_INVALID", raised.exception.code)
            self.assertEqual(before, projection._tree_fingerprint(target))

    @patch("tools.canonical_plan_projection._owner_bundle", synthetic_owner_boundary)
    def test_automatic_batch_projects_one_hundred_plans_deterministically_without_git_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-batch-automatic-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            summary = self._automatic_batch_summary(root)
            before_head = self._git(target, "rev-parse", "HEAD")

            result = projection.project_batch_automatic(
                summary,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
            )

            expected_ids = [f"P{index:04d}" for index in range(1, 101)]
            self.assertEqual("APPLIED", result["status"])
            self.assertEqual("AUTOMATIC_PLAN", result["projection_mode"])
            self.assertEqual(100, result["record_count"])
            self.assertEqual(expected_ids, result["public_ids"])
            self.assertEqual("NOT_REQUIRED", result["human_gate"])
            self.assertEqual(before_head, self._git(target, "rev-parse", "HEAD"))
            self.assertEqual(100, len(list((target / "plans").glob("P[0-9][0-9][0-9][0-9]-*/plan.md"))))
            index = yaml.safe_load((target / "plans/index.yaml").read_text(encoding="utf-8"))
            self.assertEqual(expected_ids, [item["id"] for item in index["records"]])
            evidence = json.loads((root / "state" / "BATCH-AUTO-001" / "public-projection-result.json").read_text(encoding="utf-8"))
            self.assertEqual([], projection.validate_result(evidence))
            self.assertEqual("AUTOMATIC_PLAN", evidence["projection_mode"])
            self.assertIsNone(evidence["approval_sha256"])

    @patch("tools.canonical_plan_projection._owner_bundle", synthetic_owner_boundary)
    def test_automatic_batch_projects_one_hundred_plans_through_repo_local_v2_and_replays(self) -> None:
        source = Path(os.environ.get("AAK_PROJECT_SOURCE", "/private/tmp/aa217-project"))
        if not (source / ".git").exists():
            self.skipTest("qualified Project checkout is unavailable")
        with tempfile.TemporaryDirectory(prefix="public-batch-repo-local-v2-") as temporary:
            root = Path(temporary)
            project = root / "project"
            subprocess.run(["git", "clone", "-q", str(source), str(project)], check=True)
            run_id = "BATCH-V2-001"
            (project / ".agentic-art").mkdir()
            resolution = resolve_project_root(project, run_id=run_id, project_id=run_id)
            internal = project / ".agentic-art" / "internal"
            state = project / ".agentic-art" / "state"
            summary = self._automatic_batch_summary(project / ".agentic-art", count=100, run_id=run_id)
            summary["destination_resolution"] = resolution
            authority_plans = [
                {
                    "project_id": item["project_id"],
                    "production_plan_markdown_sha256": item["production_plan_markdown_sha256"],
                }
                for item in summary["projects"]
            ]
            summary["automatic_plan_authority"] = projection.build_automatic_plan_authority(
                producer="tools/batch_run.py",
                source_status="PASSED",
                source_id=run_id,
                source_sha256=projection.sha256_hex({"projects": sorted(authority_plans, key=lambda item: item["project_id"])}),
                destination_resolution=resolution,
            )
            before_head = self._git(project, "rev-parse", "HEAD")
            result = projection.project_batch_automatic(
                summary,
                internal_output_root=internal,
                public_projection_root=project,
                state_root=state,
            )
            self.assertEqual("APPLIED", result["status"])
            self.assertEqual(100, result["record_count"])
            self.assertEqual(before_head, self._git(project, "rev-parse", "HEAD"))
            self.assertEqual(101, len(list((project / "plans").glob("P[0-9][0-9][0-9][0-9]-*/plan.md"))))
            replay = projection.project_batch_automatic(
                summary,
                internal_output_root=internal,
                public_projection_root=project,
                state_root=state,
            )
            self.assertEqual("ALREADY_PROJECTED", replay["status"])
            self.assertEqual([], replay["changed_paths"])
            self.assertEqual(before_head, self._git(project, "rev-parse", "HEAD"))
            evidence = json.loads((state / run_id / "public-projection-result.json").read_text(encoding="utf-8"))
            self.assertEqual("AUTOMATIC_PLAN", evidence["projection_mode"])
            self.assertEqual(100, len(evidence["source_refs"]))

            rollback_project = root / "rollback-project"
            subprocess.run(["git", "clone", "-q", str(source), str(rollback_project)], check=True)
            (rollback_project / ".agentic-art").mkdir()
            rollback_id = "BATCH-V2-ROLLBACK-001"
            rollback_resolution = resolve_project_root(rollback_project, run_id=rollback_id, project_id=rollback_id)
            rollback_summary = self._automatic_batch_summary(rollback_project / ".agentic-art", count=3, run_id=rollback_id)
            rollback_summary["destination_resolution"] = rollback_resolution
            rollback_plans = [
                {
                    "project_id": item["project_id"],
                    "production_plan_markdown_sha256": item["production_plan_markdown_sha256"],
                }
                for item in rollback_summary["projects"]
            ]
            rollback_summary["automatic_plan_authority"] = projection.build_automatic_plan_authority(
                producer="tools/batch_run.py",
                source_status="PASSED",
                source_id=rollback_id,
                source_sha256=projection.sha256_hex({"projects": sorted(rollback_plans, key=lambda item: item["project_id"])}),
                destination_resolution=rollback_resolution,
            )
            rollback_before = projection._tree_fingerprint(rollback_project)
            rollback_result = projection.project_batch_automatic(
                rollback_summary,
                internal_output_root=rollback_project / ".agentic-art" / "internal",
                public_projection_root=rollback_project,
                state_root=rollback_project / ".agentic-art" / "state",
                fail_after=1,
            )
            self.assertEqual("FAILED", rollback_result["status"])
            self.assertEqual(rollback_before, projection._tree_fingerprint(rollback_project))
            self.assertEqual(1, len(list((rollback_project / "plans").glob("P[0-9][0-9][0-9][0-9]-*/plan.md"))))

    @patch("tools.canonical_plan_projection._owner_bundle", synthetic_owner_boundary)
    def test_automatic_batch_policy_failure_is_all_or_nothing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-batch-policy-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            summary = self._automatic_batch_summary(root, count=3, run_id="BATCH-AUTO-POLICY-001")
            source = root / "internal" / "batch" / "BATCH-AUTO-POLICY-001" / "production" / "batch-plan-002" / "03_plan" / "production-plan.md"
            unsafe = b"# unsafe plan\n\nPRIVATE_RAW: must never be public\n"
            source.write_bytes(unsafe)
            digest = hashlib.sha256(unsafe).hexdigest()
            target_project = next(item for item in summary["projects"] if item["project_id"] == "batch-plan-002")
            target_project["production_plan_sha256"] = digest
            target_project["production_plan_markdown_sha256"] = digest
            authority_plans = [
                {
                    "project_id": item["project_id"],
                    "production_plan_markdown_sha256": item["production_plan_markdown_sha256"],
                }
                for item in summary["projects"]
            ]
            summary["automatic_plan_authority"] = projection.build_automatic_plan_authority(
                producer="tools/batch_run.py",
                source_status="PASSED",
                source_id=summary["run_id"],
                source_sha256=projection.sha256_hex({"projects": sorted(authority_plans, key=lambda item: item["project_id"])}),
                destination_resolution=summary["destination_resolution"],
            )
            before = projection._tree_fingerprint(target)

            result = projection.project_batch_automatic(
                summary,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
            )

            self.assertEqual("BLOCKED_POLICY", result["status"])
            self.assertIn("FORBIDDEN_CONTENT", set(result["finding_codes"]))
            self.assertEqual([], result["changed_paths"])
            self.assertEqual(before, projection._tree_fingerprint(target))
            self.assertFalse(any((target / "plans").glob("P[0-9][0-9][0-9][0-9]-*")))
            evidence = json.loads((root / "state" / "BATCH-AUTO-POLICY-001" / "public-projection-result.json").read_text(encoding="utf-8"))
            self.assertEqual([], projection.validate_result(evidence))

    @patch("tools.canonical_plan_projection._owner_bundle", synthetic_owner_boundary)
    def test_automatic_batch_failure_rolls_back_staged_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-batch-rollback-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            summary = self._automatic_batch_summary(root, count=3, run_id="BATCH-AUTO-ROLLBACK-001")
            before = projection._tree_fingerprint(target)

            result = projection.project_batch_automatic(
                summary,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
                fail_after=2,
            )

            self.assertEqual("FAILED", result["status"])
            self.assertEqual([], result["changed_paths"])
            self.assertEqual(before, projection._tree_fingerprint(target))
            self.assertFalse(any((target / "plans").glob("P[0-9][0-9][0-9][0-9]-*")))
            evidence = json.loads((root / "state" / "BATCH-AUTO-ROLLBACK-001" / "public-projection-result.json").read_text(encoding="utf-8"))
            self.assertEqual([], projection.validate_result(evidence))

    def test_init_target_is_explicit_and_scaffolds_only_missing_layout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-target-init-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            before = projection._tree_fingerprint(target)
            dry_run = projection.init_target(target, apply=False)
            self.assertEqual("DRY_RUN_READY", dry_run["status"])
            self.assertEqual([], dry_run["changed_paths"])
            self.assertEqual(before, projection._tree_fingerprint(target))
            applied = projection.init_target(target, apply=True)
            self.assertEqual("APPLIED", applied["status"])
            self.assertEqual(6, len(applied["changed_paths"]))
            self.assertTrue((target / "public-project.yaml").exists())
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            replay = projection.init_target(target, apply=False)
            self.assertEqual("DRY_RUN_READY", replay["status"])
            self.assertEqual([], replay["planned_paths"])

    def test_project_dry_run_is_metadata_only_deterministic_and_create_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-project-plan-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            request_path = self._prepared_public_request(root)
            before = projection._tree_fingerprint(target)
            result = projection.project_dry_run(
                request_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
            )
            self.assertEqual("DRY_RUN_READY", result["status"])
            self.assertEqual(["P0001"], result["public_ids"])
            self.assertEqual([], result["changed_paths"])
            self.assertIn("plans/P0001-example-plan/plan.md", result["planned_paths"])
            self.assertEqual(before, result["target"]["before_fingerprint"])
            self.assertEqual(before, result["target"]["after_fingerprint"])
            self.assertEqual(before, projection._tree_fingerprint(target))
            self.assertFalse((target / "plans/P0001-example-plan").exists())
            evidence = root / "state" / "PUBLIC-PLAN-001" / "public-projection-result.json"
            self.assertTrue(evidence.exists())
            self.assertEqual([], projection.validate_result(json.loads(evidence.read_text(encoding="utf-8"))))
            replay = projection.project_dry_run(
                request_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
            )
            self.assertEqual(result, replay)

    def test_project_apply_requires_matching_human_approval_and_is_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-project-apply-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            head_before = self._git(target, "rev-parse", "HEAD")
            request_path = self._prepared_public_request(root, "PUBLIC-APPLY-001")
            approval_path = self._approval_for(root, request_path)
            before = projection._tree_fingerprint(target)

            applied = projection.project_apply(
                request_path,
                approval_path=approval_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
                now=datetime(2026, 9, 5, tzinfo=timezone.utc),
            )
            self.assertEqual("APPLIED", applied["status"])
            self.assertEqual(["P0001"], applied["public_ids"])
            self.assertEqual(len(applied["changed_paths"]), applied["target"]["mutation_count"])
            self.assertNotEqual(before, applied["target"]["after_fingerprint"])
            self.assertEqual(head_before, self._git(target, "rev-parse", "HEAD"))
            self.assertEqual([], applied["remote_operations"])
            self.assertEqual([], projection.validate_result(applied))
            self.assertEqual("public", yaml.safe_load((target / "plans/P0001-example-plan/metadata.yaml").read_text(encoding="utf-8"))["visibility"])
            metadata_text = (target / "plans/P0001-example-plan/metadata.yaml").read_text(encoding="utf-8")
            self.assertNotIn("agentic-art-production", metadata_text)
            self.assertNotIn("RUN-PROJECT-001", metadata_text)
            self.assertNotIn(str(root), metadata_text)

            replay = projection.project_apply(
                request_path,
                approval_path=approval_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state-replay",
                now=datetime(2026, 9, 5, tzinfo=timezone.utc),
            )
            self.assertEqual("ALREADY_PROJECTED", replay["status"])
            self.assertEqual([], replay["changed_paths"])
            self.assertEqual(0, replay["target"]["mutation_count"])
            self.assertEqual(replay["target"]["before_fingerprint"], replay["target"]["after_fingerprint"])
            self.assertEqual([], projection.validate_result(replay))

    def test_project_apply_blocks_missing_or_mismatched_approval_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-project-human-gate-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            request_path = self._prepared_public_request(root, "PUBLIC-HUMAN-001")
            before = projection._tree_fingerprint(target)
            missing = projection.project_apply(
                request_path,
                approval_path=None,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state-missing",
                now=datetime(2026, 9, 5, tzinfo=timezone.utc),
            )
            self.assertEqual("BLOCKED_HUMAN", missing["status"])
            self.assertIn("MISSING_APPROVAL", {item["code"] for item in missing["findings"]})
            self.assertEqual(before, projection._tree_fingerprint(target))

            mismatched = self._approval_for(root, request_path, request_hash="f" * 64)
            result = projection.project_apply(
                request_path,
                approval_path=mismatched,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state-mismatch",
                now=datetime(2026, 9, 5, tzinfo=timezone.utc),
            )
            self.assertEqual("BLOCKED_HUMAN", result["status"])
            self.assertIn("APPROVAL_MISMATCH", {item["code"] for item in result["findings"]})
            self.assertEqual(before, projection._tree_fingerprint(target))
            self.assertEqual([], projection.validate_result(result))

    def test_project_apply_conflict_preserves_existing_record_and_rollback_restores_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-project-recovery-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            request_path = self._prepared_public_request(root, "PUBLIC-RECOVERY-001")
            approval_path = self._approval_for(root, request_path)
            before = projection._tree_fingerprint(target)
            failed = projection.project_apply(
                request_path,
                approval_path=approval_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state-failed",
                now=datetime(2026, 9, 5, tzinfo=timezone.utc),
                fail_after=1,
            )
            self.assertEqual("FAILED", failed["status"])
            self.assertEqual([], failed["changed_paths"])
            self.assertEqual(before, projection._tree_fingerprint(target))
            self.assertFalse((target / "plans/P0001-example-plan").exists())
            self.assertEqual([], projection.validate_result(failed))

            applied = projection.project_apply(
                request_path,
                approval_path=approval_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state-success",
                now=datetime(2026, 9, 5, tzinfo=timezone.utc),
            )
            self.assertEqual("APPLIED", applied["status"])
            body = target / "plans/P0001-example-plan/plan.md"
            body.write_text("# human changed this\n", encoding="utf-8")
            conflict_before = body.read_bytes()
            conflict = projection.project_apply(
                request_path,
                approval_path=approval_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state-conflict",
                now=datetime(2026, 9, 5, tzinfo=timezone.utc),
            )
            self.assertEqual("BLOCKED_CONFLICT", conflict["status"])
            self.assertIn("TARGET_CONFLICT", {item["code"] for item in conflict["findings"]})
            self.assertEqual(conflict_before, body.read_bytes())

    def test_project_dry_run_blocks_unknown_clearance_without_target_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-project-policy-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            request_path = self._prepared_public_request(root, "PUBLIC-POLICY-001")
            request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
            request["records"][0]["publication"]["visibility"] = "unknown"
            request["records"][0]["publication"]["rights_status"] = "unknown"
            request["records"][0]["publication"]["consent_status"] = "unknown"
            for file in request["records"][0]["files"]:
                file["rights_status"] = "unknown"
            request_path.write_bytes(projection._request_yaml_bytes(request))
            before = projection._tree_fingerprint(target)
            result = projection.project_dry_run(
                request_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
            )
            self.assertEqual("BLOCKED_POLICY", result["status"])
            self.assertEqual([], result["public_ids"])
            self.assertEqual([], result["planned_paths"])
            self.assertEqual(before, projection._tree_fingerprint(target))
            self.assertIn("UNKNOWN_CLEARANCE", {finding["code"] for finding in result["findings"]})

    def test_public_ids_include_retired_numbers_and_existing_content_conflicts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-project-index-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            request_path = self._prepared_public_request(root, "PUBLIC-INDEX-001")
            request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
            source = request["records"][0]["source"]
            index = {
                "version": 1,
                "records": [],
                "retired_ids": ["P0001"],
            }
            (target / "plans/index.yaml").write_bytes(projection._request_yaml_bytes(index))
            self._git(target, "add", "plans/index.yaml")
            self._git(target, "commit", "-m", "retire first plan id")
            result = projection.project_dry_run(
                request_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
            )
            self.assertEqual("DRY_RUN_READY", result["status"])
            self.assertEqual(["P0002"], result["public_ids"])

            conflict_index = {
                "version": 1,
                "records": [{
                    "id": "P0002",
                    "slug": "example-plan",
                    "title": "Example public plan",
                    "path": "plans/P0002-example-plan",
                    "source_key": f"plan:{source['canonical_sha256']}",
                    "content_sha256": "e" * 64,
                    "status": "ready-for-publication",
                    "visibility": "public",
                    "rights_status": "cleared",
                }],
                "retired_ids": ["P0001"],
            }
            (target / "plans/index.yaml").write_bytes(projection._request_yaml_bytes(conflict_index))
            self._git(target, "add", "plans/index.yaml")
            self._git(target, "commit", "-m", "add conflicting public index")
            before = projection._tree_fingerprint(target)
            blocked = projection.project_dry_run(
                request_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state-conflict",
            )
            self.assertEqual("BLOCKED_CONFLICT", blocked["status"])
            self.assertIn("TARGET_CONFLICT", {finding["code"] for finding in blocked["findings"]})
            self.assertEqual(before, projection._tree_fingerprint(target))

    def test_project_cli_uses_target_override_and_keeps_stdout_path_free(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-project-cli-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            request_path = self._prepared_public_request(root, "PUBLIC-CLI-001")
            profile = root / "destinations-cli.yaml"
            profile.write_text(yaml.safe_dump({
                "contract_version": "output-destinations/v1",
                "profile": "public-cli-test",
                "destinations": {
                    "state_root": str(root / "state"),
                    "internal_output_root": str(root / "internal"),
                },
            }, sort_keys=False), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = projection.main([
                    "project", "--request", str(request_path), "--destinations-file", str(profile),
                    "--target-root", str(target), "--dry-run",
                ])
            self.assertEqual(0, code)
            rendered = output.getvalue()
            self.assertNotIn(str(root), rendered)
            payload = json.loads(rendered)
            self.assertEqual("DRY_RUN_READY", payload["status"])
            self.assertEqual(1, payload["record_count"])
            self.assertEqual(["P0001"], payload["public_ids"])

            approval_path = self._approval_for(root, request_path)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = projection.main([
                    "project", "--request", str(request_path), "--approval", str(approval_path),
                    "--destinations-file", str(profile), "--target-root", str(target), "--apply",
                ])
            self.assertEqual(0, code)
            self.assertNotIn(str(root), output.getvalue())
            self.assertEqual("APPLIED", json.loads(output.getvalue())["status"])

    def test_project_dry_run_allocates_one_hundred_records_deterministically(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-project-batch-") as temporary:
            root = Path(temporary)
            target = self._new_target(root)
            projection.init_target(target, apply=True)
            self._git(target, "add", "public-project.yaml", "README.md", "plans", "works")
            self._git(target, "commit", "-m", "scaffold public project")
            records = []
            for number in range(100, 0, -1):
                slug = f"batch-{number:03d}"
                content = f"# Batch plan {number}\n".encode("utf-8")
                canonical = root / "internal" / "canonical" / f"{slug}.md"
                candidate = root / "internal" / "candidate" / f"{slug}.md"
                canonical.parent.mkdir(parents=True, exist_ok=True)
                candidate.parent.mkdir(parents=True, exist_ok=True)
                canonical.write_bytes(content)
                candidate.write_bytes(content)
                candidate_hash = hashlib.sha256(content).hexdigest()
                files = [{
                    "role": "body",
                    "source_locator": f"candidate/{slug}.md",
                    "target_locator": "plan.md",
                    "sha256": candidate_hash,
                    "mime_type": "text/markdown",
                    "rights_status": "cleared",
                }]
                records.append({
                    "record_kind": "plan",
                    "slug": slug,
                    "title": f"Batch plan {number}",
                    "source": {
                        "repository": "agentic-art-production",
                        "commit": "e" * 40,
                        "run_id": "BATCH-PLAN-001",
                        "locator": f"canonical/{slug}.md",
                        "canonical_sha256": hashlib.sha256(content).hexdigest(),
                        "sha256": projection.record_file_sha256(files),
                    },
                    "publication": {
                        "visibility": "public",
                        "rights_status": "cleared",
                        "consent_status": "cleared",
                        "attribution": [],
                    },
                    "files": files,
                })
            request = {
                "contract_version": "public-projection-request/v1",
                "projection_id": "PUBLIC-BATCH-100",
                "generated_at": "2026-09-04T00:00:00Z",
                "source_root_role": "internal_output_root",
                "records": records,
            }
            self.assertEqual([], projection.validate_request(request))
            request_path = root / "internal" / "batch-request.yaml"
            request_path.write_bytes(projection._request_yaml_bytes(request))
            first = projection.project_dry_run(
                request_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
            )
            second = projection.project_dry_run(
                request_path,
                internal_output_root=root / "internal",
                public_projection_root=target,
                state_root=root / "state",
            )
            self.assertEqual("DRY_RUN_READY", first["status"])
            self.assertEqual([f"P{number:04d}" for number in range(1, 101)], first["public_ids"])
            self.assertEqual(first, second)
            self.assertEqual(100, len([path for path in first["planned_paths"] if path.endswith("/plan.md")]))
            self.assertEqual([], projection.validate_result(first))

    def test_prepare_run_copies_one_plan_with_unknown_clearance_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-prepare-run-") as temporary:
            root = Path(temporary)
            run_id = "RUN:PREPARE-001"
            resolution = self._profile_resolution(root, run_id)
            source = root / "internal" / "production" / "example-plan" / "03_plan" / "production-plan.md"
            source.parent.mkdir(parents=True)
            content = b"# Example plan\n\nA source-owned plan.\n"
            source.write_bytes(content)
            report = {
                "run_id": run_id,
                "status": "PLAN_READY",
                "generated_at": "2026-09-04T00:00:00Z",
                "project_slug": "example-plan",
                "project_title": "Example plan",
                "plan": str(source),
                "production_plan_sha256": hashlib.sha256(content).hexdigest(),
                "production_repository": "agentic-art-production",
                "production_source_commit": "a" * 40,
                "destination_resolution": resolution,
            }
            first = projection.prepare_run_report(report, internal_output_root=root / "internal", projection_id=run_id)
            second = projection.prepare_run_report(report, internal_output_root=root / "internal", projection_id=run_id)
            self.assertEqual("PASSED", first["status"])
            self.assertEqual("ALREADY_PREPARED", second["status"])
            request_path = root / "internal" / first["request_locator"]
            request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
            self.assertEqual([], projection.validate_request(request))
            self.assertEqual(1, len(request["records"]))
            record = request["records"][0]
            self.assertEqual("unknown", record["publication"]["visibility"])
            self.assertEqual(report["production_plan_sha256"], record["source"]["canonical_sha256"])
            candidate = root / "internal" / record["files"][0]["source_locator"]
            self.assertEqual(content, candidate.read_bytes())
            self.assertFalse((root / "public-target").exists())

    def test_refresh_rehashes_candidate_without_changing_canonical_provenance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-prepare-refresh-") as temporary:
            root = Path(temporary)
            run_id = "RUN-REFRESH-001"
            resolution = self._profile_resolution(root, run_id)
            source = root / "internal" / "production" / "refresh-plan" / "03_plan" / "production-plan.md"
            source.parent.mkdir(parents=True)
            original = b"# Refresh plan\n"
            source.write_bytes(original)
            report = {
                "run_id": run_id,
                "status": "PLAN_READY",
                "generated_at": "2026-09-04T00:00:00Z",
                "project_slug": "refresh-plan",
                "project_title": "Refresh plan",
                "plan": str(source),
                "production_plan_sha256": hashlib.sha256(original).hexdigest(),
                "production_source_commit": "b" * 40,
                "destination_resolution": resolution,
            }
            prepared = projection.prepare_run_report(report, internal_output_root=root / "internal", projection_id=run_id)
            request_path = root / "internal" / prepared["request_locator"]
            before = yaml.safe_load(request_path.read_text(encoding="utf-8"))
            candidate = root / "internal" / before["records"][0]["files"][0]["source_locator"]
            candidate.write_bytes(b"# Edited public-ready candidate\n")
            refreshed = projection.refresh_request(request_path, internal_output_root=root / "internal")
            after = yaml.safe_load(request_path.read_text(encoding="utf-8"))
            self.assertEqual("REFRESHED", refreshed["status"])
            self.assertEqual(before["records"][0]["source"]["canonical_sha256"], after["records"][0]["source"]["canonical_sha256"])
            self.assertNotEqual(before["records"][0]["source"]["sha256"], after["records"][0]["source"]["sha256"])
            self.assertEqual([], projection.validate_request(after))
            self.assertEqual(before["records"][0]["publication"], after["records"][0]["publication"])

    def test_prepare_batch_handles_one_hundred_plans_in_source_key_order(self) -> None:
        with tempfile.TemporaryDirectory(prefix="public-prepare-batch-") as temporary:
            root = Path(temporary)
            run_id = "BATCH-PREPARE-001"
            resolution = self._profile_resolution(root, run_id)
            projects = []
            for number in range(100, 0, -1):
                project_id = f"batch-{number:03d}"
                content = f"# Plan {number}\n".encode("utf-8")
                source = root / "internal" / "batch" / run_id / "production" / project_id / "03_plan" / "production-plan.md"
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(content)
                projects.append({
                    "project_id": project_id,
                    "status": "PASSED",
                    "production_locator": f"run://{run_id}/production/{project_id}",
                    "production_repository": "agentic-art-production",
                    "production_source_commit": "c" * 40,
                    "production_plan_markdown_sha256": hashlib.sha256(content).hexdigest(),
                })
            summary = {
                "run_id": run_id,
                "status": "PASSED",
                "generated_at": "2026-09-04T00:00:00Z",
                "output_root_locator": f"batch/{run_id}",
                "projects": projects,
                "destination_resolution": resolution,
            }
            result = projection.prepare_batch_summary(summary, internal_output_root=root / "internal", projection_id=run_id)
            self.assertEqual("PASSED", result["status"])
            self.assertEqual(100, result["record_count"])
            request = yaml.safe_load((root / "internal" / result["request_locator"]).read_text(encoding="utf-8"))
            self.assertEqual([], projection.validate_request(request))
            self.assertEqual(100, len(request["records"]))
            keys = [record["source"]["canonical_sha256"] for record in request["records"]]
            self.assertEqual(sorted(keys), keys)
            self.assertTrue(all(record["publication"]["visibility"] == "unknown" for record in request["records"]))

    def test_unfinished_run_returns_not_available_without_inventing_work(self) -> None:
        result = projection.prepare_run_report(
            {"run_id": "RUN-PENDING-001", "status": "RESEARCH_PENDING"},
            internal_output_root=Path("/private/tmp/nonexistent-internal-root"),
            projection_id="RUN-PENDING-001",
        )
        self.assertEqual("NOT_AVAILABLE", result["status"])
        self.assertEqual(0, result["record_count"])


if __name__ == "__main__":
    unittest.main()
