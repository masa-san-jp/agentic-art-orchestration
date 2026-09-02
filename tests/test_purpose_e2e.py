from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.child_quality_gates import sha256_hex
from tools.purpose_e2e import (
    THEME,
    _offline_signals,
    _pipeline,
    canonical_evidence_hash,
    run_purpose_e2e,
    validate_purpose_e2e,
)
from tools.validate import load_yaml
from tools.visual_package_boundary import validate_visual_package_boundary


ROOT = Path(__file__).resolve().parents[1]


def _passed_child_gates() -> dict:
    manifest = load_yaml(ROOT / "config/repositories.yaml")
    return {
        "contract_version": "child-quality-gates/v1",
        "run_id": "purpose-e2e-fixture-gates",
        "manifest_hash": sha256_hex(manifest),
        "repository_count": len(manifest["repositories"]),
        "results": [
            {
                "repository": repository["id"],
                "observed_commit": repository["observed_commit"],
                "workspace_commit": repository["observed_commit"],
                "workspace_state": "MATCHED",
                "execution_mode": "immutable-archive",
                "environment_mode": "per-child",
                "quality_gate_hash": sha256_hex(repository["quality_gates"]),
                "status": "PASSED",
                "gates": [
                    {
                        "command": command,
                        "status": "PASSED",
                        "exit_code": 0,
                        "duration_ms": 0,
                        "output_redacted": "",
                        "output_truncated": False,
                        "output_sha256": "0" * 64,
                    }
                    for command in repository["quality_gates"]
                ],
            }
            for repository in manifest["repositories"]
        ],
    }


class PurposeE2ETests(unittest.TestCase):
    def test_networkless_fixture_reaches_plan_ready_without_raw_theme(self) -> None:
        with tempfile.TemporaryDirectory(prefix="purpose-e2e-test-") as directory:
            root = Path(directory)
            evidence = run_purpose_e2e(
                attempt_id="fixture-1",
                output_root=root / "output",
                state_root=root / "state",
                quality_gate_report=_passed_child_gates(),
            )
            project = root / "output" / "production" / "purpose-e2e-transparent-boundary-fixture-1"
            package = load_yaml(project / "03_plan/visual-package.yaml")
            self.assertEqual("READY", package["status"])
            self.assertEqual("BOARD", package["board"]["kind"])
            self.assertEqual("MOCKUP", package["mockup"]["kind"])
            self.assertTrue((project / package["board"]["relative_path"]).is_file())
            self.assertTrue((project / package["mockup"]["relative_path"]).is_file())
            self.assertIn("](visual-package/visual-reference-board.svg)", (project / "03_plan/production-plan.md").read_text(encoding="utf-8"))
            self.assertIn("](visual-package/concept-mockup.svg)", (project / "03_plan/production-plan.md").read_text(encoding="utf-8"))
        self.assertEqual("PLAN_READY", evidence["terminal_status"])
        self.assertTrue(all(evidence["acceptance"].values()))
        self.assertEqual([], validate_purpose_e2e(evidence))
        self.assertNotIn(THEME, json.dumps(evidence, ensure_ascii=False))
        self.assertEqual(1, evidence["autonomous"]["worker_invocation_count"])
        self.assertTrue(evidence["autonomous"]["resume_reused"])
        self.assertEqual("agentic-art-production", evidence["production"]["source_repository"])
        self.assertEqual("BOARD", evidence["production"]["visual_package"]["board"]["kind"])
        self.assertEqual("MOCKUP", evidence["production"]["visual_package"]["mockup"]["kind"])

    def test_visual_package_missing_link_hash_provenance_and_rights_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="purpose-e2e-visual-boundary-") as directory:
            root = Path(directory)
            run_purpose_e2e(attempt_id="boundary-1", output_root=root / "output", state_root=root / "state")
            project = root / "output" / "production" / "purpose-e2e-transparent-boundary-boundary-1"
            package_path = project / "03_plan/visual-package.yaml"
            package = load_yaml(package_path)
            manifest = load_yaml(ROOT / "config/repositories.yaml")
            production_commit = next(item["observed_commit"] for item in manifest["repositories"] if item["id"] == "agentic-art-production")
            kwargs = {"project_root": project, "markdown_path": project / "03_plan/production-plan.md", "production_commit": production_commit, "run_id": "PURPOSE-E2E:boundary-1", "fixture_only": True}
            self.assertEqual([], validate_visual_package_boundary(package, **kwargs))

            missing_board = copy.deepcopy(package)
            missing_board["board"] = None
            self.assertTrue(validate_visual_package_boundary(missing_board, **kwargs))
            missing_mockup = copy.deepcopy(package)
            missing_mockup["mockup"] = None
            self.assertTrue(validate_visual_package_boundary(missing_mockup, **kwargs))
            broken_link = copy.deepcopy(package)
            broken_link["board"]["relative_path"] = "03_plan/visual-package/missing.svg"
            self.assertTrue(validate_visual_package_boundary(broken_link, **kwargs))
            missing_provenance = copy.deepcopy(package)
            missing_provenance["board"]["provenance"]["source_commit"] = None
            self.assertTrue(validate_visual_package_boundary(missing_provenance, **kwargs))
            unknown_rights = copy.deepcopy(package)
            unknown_rights["board"]["safety"]["rights_status"] = "UNKNOWN"
            self.assertTrue(validate_visual_package_boundary(unknown_rights, **kwargs))
            board_path = project / package["board"]["relative_path"]
            board_path.write_bytes(board_path.read_bytes() + b"<!-- tampered -->")
            self.assertTrue(validate_visual_package_boundary(package, **kwargs))
            board_path.unlink()
            self.assertTrue(validate_visual_package_boundary(package, **kwargs))

    def test_three_networkless_runs_have_one_canonical_hash(self) -> None:
        hashes: list[str] = []
        with tempfile.TemporaryDirectory(prefix="purpose-e2e-determinism-") as directory:
            root = Path(directory)
            for index in range(1, 4):
                evidence = run_purpose_e2e(
                    attempt_id=f"fixture-{index}",
                    output_root=root / f"output-{index}",
                    state_root=root / f"state-{index}",
                    quality_gate_report=_passed_child_gates(),
                )
                self.assertEqual([], validate_purpose_e2e(evidence))
                hashes.append(canonical_evidence_hash(evidence))
        self.assertEqual(1, len(set(hashes)))

    def test_single_anchor_reaches_pipeline_as_limited_diversity(self) -> None:
        manifest = load_yaml(ROOT / "config/repositories.yaml")
        signals = _offline_signals(manifest)
        self_records = [record for record in signals if record.get("signal_kind") == "self"]
        for record in self_records[1:]:
            record["domain"]["self_model"]["tensions"] = []
            record["domain"]["self_model"]["recurring_patterns"] = []
        pipeline = _pipeline(
            signals,
            project_id="project-single-anchor",
            generated_at="2026-08-28T00:00:00+09:00",
        )
        self.assertEqual(1, pipeline["diversity"]["eligible_anchor_count"])
        self.assertEqual("PASS_LIMITED_DIVERSITY", pipeline["diversity"]["status"])
        self.assertEqual(1, pipeline["selection"]["selected_count"])

    def test_live_lane_requires_clean_pin_matched_workspace(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "workspace-root"):
            run_purpose_e2e(
                attempt_id="live-1",
                lane="live-private",
                output_root=Path(tempfile.mkdtemp(prefix="purpose-e2e-live-output-")),
                state_root=Path(tempfile.mkdtemp(prefix="purpose-e2e-live-state-")),
            )

    def test_unqualified_child_gates_do_not_claim_acceptance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="purpose-e2e-gates-") as directory:
            root = Path(directory)
            evidence = run_purpose_e2e(
                attempt_id="fixture-gates",
                output_root=root / "output",
                state_root=root / "state",
            )
        self.assertFalse(evidence["acceptance"]["child_quality_gates_passed"])
        self.assertTrue(all(item["status"] == "NOT_RUN" for item in evidence["quality_gates"]))
        self.assertTrue(validate_purpose_e2e(evidence))


if __name__ == "__main__":
    unittest.main()
