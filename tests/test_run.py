from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("orchestration_run", ROOT / "tools/run.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class MechanicalStepTests(unittest.TestCase):
    def test_a_failing_tool_stops_the_run(self):
        """A run that continued past a failed step would report progress it did not make."""
        with self.assertRaises(MODULE.StepFailure):
            MODULE._run_tool(["tools/does_not_exist.py"], "python3")

    def test_failure_names_the_tool_that_failed(self):
        try:
            MODULE._run_tool(["tools/does_not_exist.py"], "python3")
        except MODULE.StepFailure as exc:
            self.assertIn("does_not_exist", str(exc))


class BatchGenerationTests(unittest.TestCase):
    """A hundred plans cannot start from a hundred hand-typed commands."""

    SPEC = importlib.util.spec_from_file_location(
        "orchestration_request", ROOT / "tools/build_research_request.py")

    def setUp(self):
        module = importlib.util.module_from_spec(self.SPEC)
        assert self.SPEC and self.SPEC.loader
        self.SPEC.loader.exec_module(module)
        self.request = module

    @staticmethod
    def _proposition(identifier: str, signal_ids: list[str]) -> dict:
        return {"proposition_id": identifier,
                "normalized_signals": [{"signal_id": value} for value in signal_ids]}

    def test_two_studies_resting_on_the_same_signals_are_refused(self):
        same = [self._proposition("proposition:a", ["x", "y"]),
                self._proposition("proposition:b", ["y", "x"])]

        with self.assertRaises(self.request.RequestError):
            self.request._assert_distinct_signal_sets(same)

    def test_distinct_signal_sets_pass(self):
        distinct = [self._proposition("proposition:a", ["x", "y"]),
                    self._proposition("proposition:b", ["x", "z"])]

        self.request._assert_distinct_signal_sets(distinct)

    def test_a_slug_is_derived_from_what_the_proposition_is_made_of(self):
        used: set = set()

        slug = self.request._slug_for(self._proposition("proposition:5ab4c437b82b", []), "harmony", used)

        self.assertIn("5ab4c437b82b", slug)
        self.assertTrue(slug.startswith("harmony-"))

    def test_a_repeated_slug_gets_a_distinct_one_rather_than_colliding(self):
        used = {"harmony-abc"}

        slug = self.request._slug_for(self._proposition("proposition:abc", []), "harmony", used)

        self.assertNotIn(slug, used)

    def test_the_signal_set_ignores_the_order_the_signals_arrived_in(self):
        first = self.request._signal_set(self._proposition("p", ["b", "a"]))
        second = self.request._signal_set(self._proposition("q", ["a", "b"]))

        self.assertEqual(first, second)


class ChildStepTests(unittest.TestCase):
    """A resumed run re-enters steps it already took, so a child tool's refusal is not always a failure."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _tool(self, name: str, body: str) -> str:
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return name

    def test_a_conflicting_step_is_reported_as_already_done(self):
        tool = self._tool("conflict.py", "import sys\nprint('CONFLICT: handoff already in place')\nsys.exit(1)\n")

        result = MODULE._run_child(self.root, [tool], sys.executable, allow_conflict=True)

        self.assertEqual("ALREADY_DONE", result["status"])

    def test_a_step_that_is_not_ready_yet_is_reported_as_not_ready(self):
        tool = self._tool("pending.py", "import sys\nprint('project is not complete')\nsys.exit(1)\n")

        result = MODULE._run_child(self.root, [tool], sys.executable, allow_failure=True)

        self.assertEqual("NOT_READY", result["status"])

    def test_an_unexpected_child_failure_stops_the_run(self):
        tool = self._tool("broken.py", "import sys\nprint('unreadable manifest')\nsys.exit(1)\n")

        with self.assertRaises(MODULE.StepFailure):
            MODULE._run_child(self.root, [tool], sys.executable)

    def test_child_output_that_is_not_json_still_counts_as_a_passed_step(self):
        tool = self._tool("plain.py", "print('wrote the plan')\n")

        result = MODULE._run_child(self.root, [tool], sys.executable)

        self.assertEqual("PASSED", result["status"])


class ResearchPendingTests(unittest.TestCase):
    """When the research is not written yet the run names the remaining work instead of stopping silently."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_the_pending_report_says_how_the_work_is_judged_done(self):
        report = MODULE._at_research(self.work, "RUN001", "調和", [], Path("/research"), "harmony")

        self.assertEqual("RESEARCH_PENDING", report["status"])
        self.assertTrue(report["next_action"]["acceptance"])
        self.assertTrue(report["next_action"]["resume"])

    def test_the_pending_report_is_written_to_the_run_state(self):
        MODULE._at_research(self.work, "RUN001", "調和", [], Path("/research"), "harmony")

        written = json.loads((self.work / "run.json").read_text(encoding="utf-8"))
        self.assertEqual("RESEARCH_PENDING", written["status"])


class HandoverArgumentTests(unittest.TestCase):
    def test_naming_only_one_of_the_two_repositories_stops_the_run(self):
        """With one root missing, the production step would run in whatever directory is current."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MODULE.StepFailure):
                MODULE.run("調和", Path(tmp), Path(tmp), "RUN001", "artistic-research",
                           "harmony", "調和", "2026-08-20T00:00:00+09:00", sys.executable,
                           research_root=Path(tmp))


if __name__ == "__main__":
    unittest.main()


class HandoffNumberingTests(unittest.TestCase):
    """A fixed handoff id only works the first time, and every project after that is refused."""

    def _project(self, root: Path, slug: str, handoff: str | None = None) -> None:
        production = root / "projects" / slug / "05_production"
        production.mkdir(parents=True, exist_ok=True)
        if handoff is not None:
            (production / "production-handoff.yaml").write_text(handoff, encoding="utf-8")

    def test_a_project_without_a_handoff_starts_at_the_first_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root, "study")

            self.assertEqual(
                MODULE._next_handoff(root, "study"),
                {"handoff_id": "HO001", "revision": 1, "supersedes": None},
            )

    def test_a_project_with_a_handoff_gets_the_next_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root, "study", "handoff_id: HO011\nrevision: 11\n")

            self.assertEqual(
                MODULE._next_handoff(root, "study"),
                {"handoff_id": "HO012", "revision": 12, "supersedes": "HO011"},
            )

    def test_an_unreadable_handoff_does_not_silently_restart_the_numbering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root, "study", "handoff_id: not-an-id\n")

            with self.assertRaises(MODULE.StepFailure):
                MODULE._next_handoff(root, "study")
