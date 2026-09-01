from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pin_adopt import PinAdoptError, apply_report, occurrences
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


if __name__ == "__main__":
    unittest.main()
