from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pin_adopt import PinAdoptError, apply_report, evaluate, main as pin_adopt_main, occurrences
from tools.validate import validate_pin_adoption


ROOT = Path(__file__).resolve().parents[1]
COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


def _report(status: str, adoptable: bool, files: list[str]) -> dict:
    return {
        "contract_version": "pin-adoption/v1",
        "workspace_root": "/tmp/workspace",
        "adoptable_count": 1 if adoptable else 0,
        "blocked_count": 0,
        "status": status,
        "repositories": [{
            "repository": "child",
            "current_pin": COMMIT_A,
            "candidate_commit": COMMIT_B,
            "commits_ahead": 2,
            "child_gate_status": "PASSED" if adoptable else "FAILED",
            "adoptable": adoptable,
            "reason": None if adoptable else "child quality gates are FAILED at the candidate commit",
            "occurrences": files,
        }],
    }


class OccurrenceTests(unittest.TestCase):
    """The pin is repeated across the repository, so finding one of them is not finding the pin."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        (self.root / "config/repositories.yaml").write_text(f"observed_commit: {COMMIT_A}\n", encoding="utf-8")
        (self.root / "fixture.json").write_text(f'{{"commit": "{COMMIT_A}"}}\n', encoding="utf-8")
        (self.root / "unrelated.md").write_text("nothing here\n", encoding="utf-8")
        self.addCleanup(self.temporary.cleanup)

    def test_every_file_repeating_the_pin_is_found(self):
        found = occurrences(self.root, COMMIT_A)

        self.assertIn("config/repositories.yaml", found)
        self.assertIn("fixture.json", found)

    def test_a_file_without_the_pin_is_not_listed(self):
        self.assertNotIn("unrelated.md", occurrences(self.root, COMMIT_A))

    def test_generated_data_is_left_out_of_the_rewrite(self):
        (self.root / "data").mkdir()
        (self.root / "data/snapshot.json").write_text(f'{{"head": "{COMMIT_A}"}}\n', encoding="utf-8")

        self.assertNotIn("data/snapshot.json", occurrences(self.root, COMMIT_A))


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        self.manifest = self.root / "config/repositories.yaml"
        self.manifest.write_text(f"observed_commit: {COMMIT_A}\n", encoding="utf-8")
        self.fixture = self.root / "fixture.json"
        self.fixture.write_text(f'{{"commit": "{COMMIT_A}"}}\n', encoding="utf-8")
        self.addCleanup(self.temporary.cleanup)

    def test_adoption_rewrites_every_place_the_pin_appears(self):
        written = apply_report(self.root, _report("READY", True, ["config/repositories.yaml", "fixture.json"]))

        self.assertEqual(["config/repositories.yaml", "fixture.json"], written)
        self.assertIn(COMMIT_B, self.manifest.read_text(encoding="utf-8"))
        self.assertIn(COMMIT_B, self.fixture.read_text(encoding="utf-8"))

    def test_a_blocked_report_writes_nothing(self):
        with self.assertRaises(PinAdoptError):
            apply_report(self.root, _report("BLOCKED", False, []))

        self.assertIn(COMMIT_A, self.manifest.read_text(encoding="utf-8"))


class ReportContractTests(unittest.TestCase):
    def test_a_ready_report_with_recorded_occurrences_validates(self):
        self.assertEqual([], validate_pin_adoption(_report("READY", True, ["config/repositories.yaml"])))

    def test_claiming_ready_while_adopting_nothing_is_refused(self):
        errors = validate_pin_adoption(_report("READY", False, []))

        self.assertTrue(errors)

    def test_adopting_without_recording_where_the_pin_lives_is_refused(self):
        errors = validate_pin_adoption(_report("READY", True, []))

        self.assertTrue(errors)


class CommandTests(unittest.TestCase):
    def test_asking_for_both_modes_is_refused(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/pin_adopt.py"), "--dry-run", "--apply"],
            capture_output=True, text=True, check=False)

        self.assertNotEqual(0, result.returncode)

    def test_asking_for_neither_mode_is_refused(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/pin_adopt.py")],
            capture_output=True, text=True, check=False)

        self.assertNotEqual(0, result.returncode)

    def test_python_root_is_forwarded_to_child_quality_gates(self):
        manifest = {"repositories": [{"id": "child", "path": "child", "observed_commit": COMMIT_A}]}
        candidate = {"head": COMMIT_B, "reason": None, "commits_ahead": 1}
        gates = {"results": [{"repository": "child", "status": "PASSED"}]}
        python_root = Path("/tmp/child-environments")

        with patch("tools.pin_adopt.load_yaml", return_value=manifest), patch(
            "tools.pin_adopt._candidate", return_value=candidate
        ), patch("tools.pin_adopt.occurrences", return_value=["config/repositories.yaml"]), patch(
            "tools.pin_adopt.run_child_quality_gates", return_value=gates
        ) as run_gates:
            evaluate(Path("/tmp/repository"), Path("/tmp/workspace"), python_root=python_root)

        self.assertEqual(
            {
                "run_id": "pin-adopt",
                "python_root": python_root,
            },
            run_gates.call_args.kwargs,
        )

    def test_python_root_is_omitted_when_not_configured(self):
        manifest = {"repositories": [{"id": "child", "path": "child", "observed_commit": COMMIT_A}]}
        candidate = {"head": COMMIT_B, "reason": None, "commits_ahead": 1}
        gates = {"results": [{"repository": "child", "status": "PASSED"}]}

        with patch("tools.pin_adopt.load_yaml", return_value=manifest), patch(
            "tools.pin_adopt._candidate", return_value=candidate
        ), patch("tools.pin_adopt.occurrences", return_value=["config/repositories.yaml"]), patch(
            "tools.pin_adopt.run_child_quality_gates", return_value=gates
        ) as run_gates:
            evaluate(Path("/tmp/repository"), Path("/tmp/workspace"))

        self.assertEqual({"run_id": "pin-adopt"}, run_gates.call_args.kwargs)

    def test_cli_passes_python_root_to_evaluate(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pin-adoption.json"
            report = _report("UNCHANGED", False, [])
            with patch("tools.pin_adopt.evaluate", return_value=report) as run_evaluate:
                result = pin_adopt_main(
                    [
                        "--dry-run",
                        "--workspace-root",
                        "workspace",
                        "--python-root",
                        "python-root",
                        "--output",
                        str(output),
                    ]
                )

        self.assertEqual(0, result)
        self.assertEqual(Path.cwd() / "workspace", run_evaluate.call_args.args[1])
        self.assertEqual(Path.cwd() / "python-root", run_evaluate.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
