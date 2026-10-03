from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.pin_adopt import (
    PinAdoptError,
    apply_report,
    evaluate,
    main as pin_adopt_main,
    occurrences,
    rewritable_globs,
)
from tools.validate import validate_pin_adoption, validate_pin_adoption_scope


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
    """--apply writes only occurrences inside the config/pin-adoption-scope.yaml allowlist."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        self.manifest = self.root / "config/repositories.yaml"
        self.manifest.write_text(f"observed_commit: {COMMIT_A}\n", encoding="utf-8")
        (self.root / "tests/fixtures").mkdir(parents=True)
        self.fixture = self.root / "tests/fixtures/fixture.json"
        self.fixture.write_text(f'{{"commit": "{COMMIT_A}"}}\n', encoding="utf-8")
        self.addCleanup(self.temporary.cleanup)

    def test_adoption_rewrites_every_place_the_pin_appears(self):
        written, preserved = apply_report(
            self.root, _report("READY", True, ["config/repositories.yaml", "tests/fixtures/fixture.json"])
        )

        self.assertEqual(["config/repositories.yaml", "tests/fixtures/fixture.json"], written)
        self.assertEqual([], preserved)
        self.assertIn(COMMIT_B, self.manifest.read_text(encoding="utf-8"))
        self.assertIn(COMMIT_B, self.fixture.read_text(encoding="utf-8"))

    def test_a_blocked_report_writes_nothing(self):
        with self.assertRaises(PinAdoptError):
            apply_report(self.root, _report("BLOCKED", False, []))

        self.assertIn(COMMIT_A, self.manifest.read_text(encoding="utf-8"))


class ApplyPreservesHistoricalEvidenceTests(unittest.TestCase):
    """execution/ records what a past run actually observed; --apply must leave it byte-identical.

    Regression test for Issue 261: pin_adopt.py --apply previously rewrote
    execution/handoff.md and friends, turning a past observation ("merged as
    a4df0e5...") into a record of something that never happened.
    """

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        self.manifest = self.root / "config/repositories.yaml"
        self.manifest.write_text(f"observed_commit: {COMMIT_A}\n", encoding="utf-8")

        (self.root / "tests/fixtures/retrieval").mkdir(parents=True)
        self.fixture = self.root / "tests/fixtures/retrieval/index.json"
        self.fixture.write_text(f'{{"source_commit": "{COMMIT_A}"}}\n', encoding="utf-8")

        (self.root / "execution").mkdir()
        self.handoff = self.root / "execution/handoff.md"
        self.handoff_text = f"Research PR #106 is merged as {COMMIT_A}.\n"
        self.handoff.write_text(self.handoff_text, encoding="utf-8")
        self.handoff_bytes_before = self.handoff.read_bytes()

        self.state = self.root / "execution/state.yaml"
        self.state_text = f"last_completed_task: T1\nobserved_commit: {COMMIT_A}\n"
        self.state.write_text(self.state_text, encoding="utf-8")
        self.state_bytes_before = self.state.read_bytes()

        self.addCleanup(self.temporary.cleanup)

    def test_execution_evidence_is_left_byte_identical_and_fixtures_are_updated(self):
        occurrences_found = occurrences(self.root, COMMIT_A)
        self.assertIn("tests/fixtures/retrieval/index.json", occurrences_found)
        self.assertIn("execution/handoff.md", occurrences_found)
        self.assertIn("execution/state.yaml", occurrences_found)

        written, preserved = apply_report(self.root, _report("READY", True, occurrences_found))

        self.assertEqual(["config/repositories.yaml", "tests/fixtures/retrieval/index.json"], written)
        self.assertEqual(["execution/handoff.md", "execution/state.yaml"], preserved)

        # Historical evidence is untouched, byte for byte.
        self.assertEqual(self.handoff_bytes_before, self.handoff.read_bytes())
        self.assertEqual(self.handoff_text, self.handoff.read_text(encoding="utf-8"))
        self.assertEqual(self.state_bytes_before, self.state.read_bytes())
        self.assertEqual(self.state_text, self.state.read_text(encoding="utf-8"))

        # The current-pin fixture is updated.
        self.assertIn(COMMIT_B, self.fixture.read_text(encoding="utf-8"))
        self.assertNotIn(COMMIT_A, self.fixture.read_text(encoding="utf-8"))


class RewritableGlobsTests(unittest.TestCase):
    def test_the_real_allowlist_covers_manifest_and_fixtures_only(self):
        globs = rewritable_globs()

        self.assertIn("config/repositories.yaml", globs)
        self.assertIn("tests/fixtures/**", globs)
        for pattern in globs:
            self.assertFalse(pattern.startswith("execution"), pattern)
            self.assertFalse(pattern.startswith("docs"), pattern)

    def test_a_missing_allowlist_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "config/pin-adoption-scope.yaml"
            with self.assertRaises(PinAdoptError):
                rewritable_globs(missing)


class PinAdoptionScopeContractTests(unittest.TestCase):
    def test_the_real_scope_config_validates(self):
        self.assertEqual([], validate_pin_adoption_scope())

    def test_naming_execution_in_the_allowlist_is_refused(self):
        errors = validate_pin_adoption_scope(
            {"contract_version": "pin-adoption-scope/v1", "rewritable_paths": ["execution/handoff.md"]}
        )

        self.assertTrue(errors)

    def test_naming_docs_in_the_allowlist_is_refused(self):
        errors = validate_pin_adoption_scope(
            {"contract_version": "pin-adoption-scope/v1", "rewritable_paths": ["docs/aak-02-execution.md"]}
        )

        self.assertTrue(errors)


class ReportContractTests(unittest.TestCase):
    def test_a_ready_report_with_recorded_occurrences_validates(self):
        self.assertEqual([], validate_pin_adoption(_report("READY", True, ["config/repositories.yaml"])))

    def test_claiming_ready_while_adopting_nothing_is_refused(self):
        errors = validate_pin_adoption(_report("READY", False, []))

        self.assertTrue(errors)

    def test_adopting_without_recording_where_the_pin_lives_is_refused(self):
        errors = validate_pin_adoption(_report("READY", True, []))

        self.assertTrue(errors)

    def test_an_applied_report_with_preserved_occurrences_validates(self):
        report = _report("READY", True, ["config/repositories.yaml", "execution/handoff.md"])
        report["written_files"] = ["config/repositories.yaml"]
        report["preserved_occurrences"] = ["execution/handoff.md"]

        self.assertEqual([], validate_pin_adoption(report))

    def test_rewriting_execution_evidence_is_refused(self):
        report = _report("READY", True, ["config/repositories.yaml", "execution/handoff.md"])
        report["written_files"] = ["config/repositories.yaml", "execution/handoff.md"]

        errors = validate_pin_adoption(report)

        self.assertTrue(errors)

    def test_rewriting_a_docs_narrative_record_is_refused(self):
        report = _report("READY", True, ["config/repositories.yaml", "docs/aak-02-execution.md"])
        report["written_files"] = ["config/repositories.yaml", "docs/aak-02-execution.md"]

        errors = validate_pin_adoption(report)

        self.assertTrue(errors)

    def test_a_file_reported_as_both_written_and_preserved_is_refused(self):
        report = _report("READY", True, ["config/repositories.yaml"])
        report["written_files"] = ["config/repositories.yaml"]
        report["preserved_occurrences"] = ["config/repositories.yaml"]

        errors = validate_pin_adoption(report)

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
