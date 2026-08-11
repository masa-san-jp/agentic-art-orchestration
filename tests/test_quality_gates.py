from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.quality_gates import QualityGateError, run_quality_gates


def manifest_for(workspace: Path) -> dict:
    return {
        "repositories": [
            {
                "id": "pass-repo",
                "path": "pass-repo",
                "quality_gates": ["python3 pass_gate.py"],
            },
            {
                "id": "fail-repo",
                "path": "fail-repo",
                "quality_gates": ["python3 fail_gate.py"],
            },
            {
                "id": "unchanged-repo",
                "path": "unchanged-repo",
                "quality_gates": ["python3 missing.py"],
            },
        ]
    }


class QualityGateTests(unittest.TestCase):
    def test_only_changed_repositories_run_and_unchanged_is_not_run(self):
        with tempfile.TemporaryDirectory(prefix="quality-gates-") as temporary:
            root = Path(temporary)
            (root / "pass-repo").mkdir()
            (root / "pass-repo/pass_gate.py").write_text("print('pass')\n", encoding="utf-8")
            result = run_quality_gates(manifest_for(root), root, ["pass-repo"])

            self.assertEqual("PASSED", result["status"])
            self.assertFalse(result["blocking"])
            repositories = {item["repository"]: item for item in result["repositories"]}
            self.assertEqual("PASSED", repositories["pass-repo"]["status"])
            self.assertEqual("NOT_RUN", repositories["fail-repo"]["status"])
            self.assertEqual("NOT_RUN", repositories["unchanged-repo"]["status"])

    def test_failure_is_blocking_and_output_is_redacted_and_hashed(self):
        with tempfile.TemporaryDirectory(prefix="quality-gates-failure-") as temporary:
            root = Path(temporary)
            (root / "fail-repo").mkdir()
            (root / "fail-repo/fail_gate.py").write_text(
                "print('password=supersecret')\nraise SystemExit(3)\n",
                encoding="utf-8",
            )
            result = run_quality_gates(manifest_for(root), root, ["fail-repo"])

            self.assertEqual("FAILED", result["status"])
            self.assertTrue(result["blocking"])
            gate = next(item for item in result["repositories"] if item["repository"] == "fail-repo")["gates"][0]
            self.assertEqual("FAILED", gate["status"])
            self.assertEqual(3, gate["exit_code"])
            self.assertNotIn("supersecret", gate["output_redacted"])
            self.assertIn("<REDACTED>", gate["output_redacted"])
            self.assertEqual(64, len(gate["output_sha256"]))
            self.assertEqual(hashlib.sha256(gate["output_redacted"].encode()).hexdigest(), gate["output_sha256"])

    def test_shell_control_syntax_fails_without_execution(self):
        with tempfile.TemporaryDirectory(prefix="quality-gates-shell-") as temporary:
            root = Path(temporary)
            (root / "pass-repo").mkdir()
            manifest = manifest_for(root)
            manifest["repositories"][0]["quality_gates"] = ["python3 pass_gate.py; touch should-not-exist"]
            result = run_quality_gates(manifest, root, ["pass-repo"])
            repository = next(item for item in result["repositories"] if item["repository"] == "pass-repo")
            gate = repository["gates"][0]
            self.assertEqual("FAILED", gate["status"])
            self.assertIn("shell control syntax", gate["error"])
            self.assertFalse((root / "pass-repo/should-not-exist").exists())

    def test_unknown_changed_repository_is_rejected(self):
        with self.assertRaisesRegex(QualityGateError, "unknown changed repository.*remediation"):
            run_quality_gates({"repositories": []}, Path("/tmp"), ["missing"])


if __name__ == "__main__":
    unittest.main()
