from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.qualify_pin_update import (
    DEFAULT_GATE_TIMEOUT_SECONDS,
    _manifest_hash,
    _replace_pins,
    apply_qualified_pins,
    qualify_pin_update,
    workspace_candidate,
)


class PinUpdateTests(unittest.TestCase):
    def test_qualification_summary_preserves_sanitized_child_statuses(self) -> None:
        manifest = {"version": 1, "repositories": []}
        quality = {
            "results": [
                {
                    "repository": "agentic-art-production",
                    "status": "ENV_UNSATISFIED",
                    "execution_mode": "NOT_RUN",
                    "environment_mode": "per-child",
                    "gates": [
                        {
                            "command": "python3 tools/validate.py --check",
                            "status": "NOT_RUN",
                            "exit_code": None,
                            "error": "dependency preflight failed",
                        }
                    ],
                }
            ]
        }
        with patch("tools.qualify_pin_update.workspace_candidate", return_value=(manifest, [])), patch(
            "tools.qualify_pin_update.validate_manifest", return_value=[]
        ), patch("tools.qualify_pin_update.run_child_quality_gates", return_value=quality):
            report = qualify_pin_update(manifest, Path("/tmp/qualification-workspace"))

        self.assertEqual(DEFAULT_GATE_TIMEOUT_SECONDS, 300)
        self.assertEqual(
            [
                {
                    "repository": "agentic-art-production",
                    "status": "ENV_UNSATISFIED",
                    "execution_mode": "NOT_RUN",
                    "environment_mode": "per-child",
                    "gates": [
                        {
                            "command": "python3 tools/validate.py --check",
                            "status": "NOT_RUN",
                            "exit_code": None,
                            "error": "dependency preflight failed",
                        }
                    ],
                }
            ],
            report["child_quality_gates"]["repositories"],
        )
        self.assertEqual("FAILED", report["status"])
        self.assertEqual("NOT_RUN", report["production_exchange"]["status"])

    def test_workspace_candidate_reads_clean_head_without_changing_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pin-update-test-") as temporary:
            root = Path(temporary)
            checkout = root / "child"
            subprocess.run(["git", "init", "-b", "main", str(checkout)], check=True, capture_output=True)
            (checkout / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(checkout), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(checkout), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "initial"], check=True, capture_output=True)
            commit = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
            manifest = {"version": 1, "workspace_root": "repos", "repositories": [{"id": "child", "path": "child", "observed_commit": "0" * 40}]}
            candidate, changes = workspace_candidate(manifest, root)
            self.assertEqual(commit, candidate["repositories"][0]["observed_commit"])
            self.assertEqual(commit, changes[0]["new_commit"])
            self.assertEqual("0" * 40, manifest["repositories"][0]["observed_commit"])

    def test_replace_pins_only_changes_requested_manifest_lines(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pin-update-manifest-") as temporary:
            path = Path(temporary) / "repositories.yaml"
            path.write_text(
                "version: 1\nrepositories:\n  - id: first\n    observed_commit: "
                + "0" * 40
                + "\n  - id: second\n    observed_commit: "
                + "1" * 40
                + "\n",
                encoding="utf-8",
            )
            _replace_pins(path, {"second": "2" * 40})
            rendered = path.read_text(encoding="utf-8")
            self.assertIn("observed_commit: " + "0" * 40, rendered)
            self.assertIn("observed_commit: " + "2" * 40, rendered)
            self.assertNotIn("observed_commit: " + "1" * 40, rendered)

    def test_apply_refuses_workspace_drift_after_qualification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pin-update-apply-") as temporary:
            root = Path(temporary)
            checkout = root / "child"
            subprocess.run(["git", "init", "-b", "main", str(checkout)], check=True, capture_output=True)
            (checkout / "README.md").write_text("first\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(checkout), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(checkout), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "first"], check=True, capture_output=True)
            first = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
            manifest = {"version": 1, "workspace_root": "repos", "repositories": [{"id": "child", "path": "child", "observed_commit": "0" * 40}]}
            candidate, changes = workspace_candidate(manifest, root)
            report = {"status": "PASSED", "candidate_manifest_hash": _manifest_hash(candidate), "changes": changes}
            (checkout / "README.md").write_text("second\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(checkout), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(checkout), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "second"], check=True, capture_output=True)
            manifest_path = root / "repositories.yaml"
            manifest_path.write_text("version: 1\nrepositories:\n  - id: child\n    observed_commit: " + "0" * 40 + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed after qualification"):
                apply_qualified_pins(manifest_path, manifest, root, report)
            self.assertIn("observed_commit: " + "0" * 40, manifest_path.read_text(encoding="utf-8"))
            self.assertNotEqual(first, "")


if __name__ == "__main__":
    unittest.main()
