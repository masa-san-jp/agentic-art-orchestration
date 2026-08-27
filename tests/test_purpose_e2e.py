from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.child_quality_gates import sha256_hex
from tools.purpose_e2e import (
    THEME,
    canonical_evidence_hash,
    run_purpose_e2e,
    validate_purpose_e2e,
)
from tools.validate import load_yaml


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
        self.assertEqual("PLAN_READY", evidence["terminal_status"])
        self.assertTrue(all(evidence["acceptance"].values()))
        self.assertEqual([], validate_purpose_e2e(evidence))
        self.assertNotIn(THEME, json.dumps(evidence, ensure_ascii=False))
        self.assertEqual(1, evidence["autonomous"]["worker_invocation_count"])
        self.assertTrue(evidence["autonomous"]["resume_reused"])

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
