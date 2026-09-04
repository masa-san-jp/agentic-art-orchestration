from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.workspace import (
    BOOTSTRAP_STATUS_EXIT_CODES,
    build_bootstrap_result,
    load_manifest,
    parse_args,
    validate_bootstrap_result,
)


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_TOOL = ROOT / "tools/workspace.py"


class WorkspaceBootstrapContractTests(unittest.TestCase):
    def _record(self, repository: dict, *, action: str = "not-run") -> dict:
        matched = action != "not-run"
        return {
            "id": repository["id"],
            "full_name": repository["full_name"],
            "path": repository["path"],
            "action": action,
            "head": repository["observed_commit"] if matched else None,
            "observed_commit": repository["observed_commit"],
            "pin_status": "MATCHED" if matched else "NOT_RUN",
            "guard_status": "PASS" if matched else "NOT_RUN",
            "finding_codes": [] if matched else ["BOOTSTRAP_NOT_READY"],
        }

    def test_clean_result_is_canonical_in_manifest_order_and_schema_valid(self) -> None:
        manifest = load_manifest()
        with tempfile.TemporaryDirectory(prefix="workspace-bootstrap-contract-") as temporary:
            root = Path(temporary) / "workspace"
            records = [self._record(repository, action="cloned") for repository in reversed(manifest["repositories"])]
            result = build_bootstrap_result(
                manifest,
                root,
                status="READY",
                repositories=records,
                changed_count=len(records),
                offline_fixture=True,
                remediations=[],
            )
            self.assertEqual("workspace-bootstrap/v1", result["contract_version"])
            self.assertEqual([item["id"] for item in manifest["repositories"]], [item["id"] for item in result["repositories"]])
            self.assertEqual(0, result["exit_code"])
            self.assertEqual([], validate_bootstrap_result(result))
            self.assertEqual(result, json.loads(json.dumps(result, sort_keys=True)))

    def test_non_ready_result_has_fixed_exit_and_sanitized_remediation(self) -> None:
        manifest = load_manifest()
        with tempfile.TemporaryDirectory(prefix="workspace-bootstrap-blocked-") as temporary:
            result = build_bootstrap_result(
                manifest,
                Path(temporary) / "workspace",
                status="BLOCKED_EXISTING_WORKSPACE",
                repositories=[self._record(repository) for repository in manifest["repositories"]],
                changed_count=0,
                offline_fixture=True,
                remediations=["inspect the existing checkout manually"],
                lock_status="BLOCKED_EXISTING",
            )
            self.assertEqual(2, result["exit_code"])
            self.assertEqual([], validate_bootstrap_result(result))
            self.assertEqual(2, BOOTSTRAP_STATUS_EXIT_CODES["BLOCKED_REMOTE_ACCESS"])
            self.assertNotIn("remote response", json.dumps(result).lower())

    def test_contract_validator_rejects_unknown_result_fields(self) -> None:
        manifest = load_manifest()
        with tempfile.TemporaryDirectory(prefix="workspace-bootstrap-closed-") as temporary:
            result = build_bootstrap_result(
                manifest,
                Path(temporary) / "workspace",
                status="FAILED",
                repositories=[self._record(repository) for repository in manifest["repositories"]],
                changed_count=0,
                offline_fixture=False,
                remediations=["bootstrap is not ready"],
                lock_status="NOT_ACQUIRED",
            )
            invalid = copy.deepcopy(result)
            invalid["credential"] = "must not be retained"
            errors = validate_bootstrap_result(invalid)
            self.assertTrue(errors)
            self.assertIn("unknown field", "\n".join(errors))

    def test_bootstrap_parser_is_opt_in_and_existing_commands_remain_parseable(self) -> None:
        with patch.object(sys, "argv", ["workspace.py", "bootstrap", "--offline-fixture", "--json", "--workspace-root", "/tmp/workspace"]):
            args = parse_args()
        self.assertEqual("bootstrap", args.command)
        self.assertTrue(args.offline_fixture)
        self.assertTrue(args.json)
        with patch.object(sys, "argv", ["workspace.py", "status", "--json"]):
            legacy_args = parse_args()
        self.assertEqual("status", legacy_args.command)
        self.assertTrue(legacy_args.json)

    def test_bootstrap_cli_emits_contract_without_cloning_or_creating_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workspace-bootstrap-cli-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            fixture = root / "fixture"
            first = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_TOOL),
                    "bootstrap",
                    "--offline-fixture",
                    "--json",
                    "--workspace-root",
                    str(workspace),
                    "--fixture-root",
                    str(fixture),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            second = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_TOOL),
                    "bootstrap",
                    "--offline-fixture",
                    "--json",
                    "--workspace-root",
                    str(workspace),
                    "--fixture-root",
                    str(fixture),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, first.returncode, first.stderr)
            self.assertEqual(1, second.returncode, second.stderr)
            self.assertEqual(first.stdout, second.stdout)
            payload = json.loads(first.stdout)
            self.assertEqual("workspace-bootstrap/v1", payload["contract_version"])
            self.assertEqual("FAILED", payload["status"])
            self.assertEqual(len(load_manifest()["repositories"]), len(payload["repositories"]))
            self.assertFalse(workspace.exists())
            self.assertFalse(fixture.exists())


if __name__ == "__main__":
    unittest.main()
