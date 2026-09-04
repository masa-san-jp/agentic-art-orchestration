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
    acquire_bootstrap_lock,
    bootstrap_workspace,
    build_bootstrap_result,
    ensure_offline_remotes,
    load_manifest,
    parse_args,
    release_bootstrap_lock,
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

    def test_bootstrap_cli_preflights_without_cloning_and_is_deterministic(self) -> None:
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
            self.assertEqual("RELEASED", payload["lock_status"])
            self.assertEqual(len(load_manifest()["repositories"]), len(payload["repositories"]))
            self.assertTrue(workspace.is_dir())
            self.assertTrue((fixture / "remotes").is_dir())
            self.assertFalse((workspace / ".agentic-art-bootstrap.lock").exists())
            self.assertTrue(all(repository["action"] == "not-run" for repository in payload["repositories"]))
            self.assertTrue(all(repository["finding_codes"] == ["NOT_RUN"] for repository in payload["repositories"]))
            self.assertEqual(0, payload["changed_count"])
            self.assertFalse(any(path.is_dir() for path in workspace.iterdir()))

    def test_existing_unsafe_checkout_blocks_without_new_clones_or_mutation(self) -> None:
        manifest = load_manifest()
        with tempfile.TemporaryDirectory(prefix="workspace-bootstrap-existing-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            fixture = root / "fixture"
            initialized = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_TOOL),
                    "init",
                    "--offline-fixture",
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
            self.assertEqual(0, initialized.returncode, initialized.stderr)
            unsafe = workspace / "self-model-notes"
            (unsafe / "untracked-bootstrap.txt").write_text("fixture\n", encoding="utf-8")
            before = {
                repository["id"]: subprocess.run(
                    ["git", "status", "--porcelain", "--untracked-files=all"],
                    cwd=workspace / repository["path"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                for repository in manifest["repositories"]
            }
            result = bootstrap_workspace(manifest, workspace, True, fixture)
            self.assertEqual("BLOCKED_EXISTING_WORKSPACE", result["status"])
            self.assertEqual(0, result["changed_count"])
            entry = next(item for item in result["repositories"] if item["id"] == "self-model")
            self.assertIn("DIRTY", entry["finding_codes"])
            self.assertIn("UNTRACKED", entry["finding_codes"])
            after = {
                repository["id"]: subprocess.run(
                    ["git", "status", "--porcelain", "--untracked-files=all"],
                    cwd=workspace / repository["path"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                for repository in manifest["repositories"]
            }
            self.assertEqual(before, after)
            self.assertFalse(any(item["action"] == "cloned" for item in result["repositories"]))

    def test_remote_access_failure_blocks_before_any_clone(self) -> None:
        manifest = load_manifest()
        with tempfile.TemporaryDirectory(prefix="workspace-bootstrap-remote-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            fixture = root / "fixture"
            ensure_offline_remotes(manifest, fixture)
            calls: list[str] = []

            def deny_one(remote: str) -> bool:
                calls.append(remote)
                return not remote.endswith("art-history.git")

            with patch("tools.workspace._remote_access_preflight", side_effect=deny_one):
                result = bootstrap_workspace(manifest, workspace, True, fixture)
            self.assertEqual("BLOCKED_REMOTE_ACCESS", result["status"])
            self.assertEqual(0, result["changed_count"])
            self.assertEqual(len(manifest["repositories"]), len(calls))
            blocked = next(item for item in result["repositories"] if item["id"] == "art-history")
            self.assertEqual(["REMOTE_ACCESS"], blocked["finding_codes"])
            self.assertFalse(workspace.exists())
            rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
            self.assertNotIn("remote response", rendered.lower())

    def test_existing_lock_blocks_without_deleting_lock(self) -> None:
        manifest = load_manifest()
        with tempfile.TemporaryDirectory(prefix="workspace-bootstrap-lock-") as temporary:
            workspace = Path(temporary) / "workspace"
            fixture = Path(temporary) / "fixture"
            self.assertTrue(acquire_bootstrap_lock(workspace, manifest))
            try:
                result = bootstrap_workspace(manifest, workspace, False, fixture)
                self.assertEqual("BLOCKED_RACE", result["status"])
                self.assertEqual("BLOCKED_EXISTING", result["lock_status"])
                self.assertTrue((workspace / ".agentic-art-bootstrap.lock").exists())
                self.assertTrue(all(item["finding_codes"] == ["RACE"] for item in result["repositories"]))
            finally:
                release_bootstrap_lock(workspace)

    def test_symlink_workspace_root_is_rejected_without_following_target(self) -> None:
        manifest = load_manifest()
        with tempfile.TemporaryDirectory(prefix="workspace-bootstrap-symlink-") as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            workspace = root / "workspace-link"
            workspace.symlink_to(target, target_is_directory=True)
            fixture = root / "fixture"
            result = bootstrap_workspace(manifest, workspace, True, fixture)
            self.assertEqual("FAILED", result["status"])
            self.assertEqual(0, result["changed_count"])
            self.assertTrue(all(item["finding_codes"] == ["INVALID_CHECKOUT"] for item in result["repositories"]))
            self.assertFalse((target / ".agentic-art-bootstrap.lock").exists())
            self.assertFalse(fixture.exists())

    def test_pin_drift_is_reported_without_checkout_or_pin_update(self) -> None:
        manifest = load_manifest()
        drifted = copy.deepcopy(manifest)
        drifted["repositories"][0]["observed_commit"] = "f" * 40
        with tempfile.TemporaryDirectory(prefix="workspace-bootstrap-pin-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            fixture = root / "fixture"
            initialized = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_TOOL),
                    "init",
                    "--offline-fixture",
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
            self.assertEqual(0, initialized.returncode, initialized.stderr)
            head_file = workspace / "self-model-notes" / ".git" / "HEAD"
            before = head_file.read_bytes()
            result = bootstrap_workspace(drifted, workspace, True, fixture)
            self.assertEqual("BLOCKED_PIN_DRIFT", result["status"])
            self.assertEqual(0, result["changed_count"])
            entry = next(item for item in result["repositories"] if item["id"] == "self-model")
            self.assertEqual("DRIFTED", entry["pin_status"])
            self.assertIn("PIN_DRIFT", entry["finding_codes"])
            self.assertEqual(before, head_file.read_bytes())


if __name__ == "__main__":
    unittest.main()
