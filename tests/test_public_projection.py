from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from tools import public_projection as projection
from tools.output_destinations import resolve_destinations
from tools.security import PUBLIC_PROJECTION_FINDING_CODES, scan_public_projection


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/public-projection"


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

    def _profile_resolution(self, root: Path, run_id: str) -> dict:
        profile = root / "destinations.yaml"
        profile.write_text(
            yaml.safe_dump({
                "contract_version": "output-destinations/v1",
                "profile": "prepare-test",
                "destinations": {
                    "state_root": str(root / "state"),
                    "internal_output_root": str(root / "internal"),
                },
            }, sort_keys=False),
            encoding="utf-8",
        )
        return resolve_destinations(profile, repository_root=ROOT, run_id=run_id)

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
