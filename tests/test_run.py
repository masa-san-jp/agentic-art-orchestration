from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.input_pipeline import run_input_pipeline
from tools.run import run
from tools.signal_bundle import build_signal_bundle


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("orchestration_run", ROOT / "tools/run.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def fixture_signals() -> list[dict]:
    return [
        json.loads((ROOT / "tests" / "fixtures" / "signal" / name).read_text(encoding="utf-8"))
        for name in ("valid_self.json", "valid_art_history.json", "valid_marketing.json")
    ]


class RunTests(unittest.TestCase):
    def bundle(self) -> dict:
        return build_signal_bundle(fixture_signals(), "2026-08-26T00:00:00+09:00")

    def test_no_intent_keeps_the_existing_v1_selection_contract(self) -> None:
        bundle = self.bundle()
        legacy = run_input_pipeline(bundle, project_id="run-test", seed_input="seed")
        current = run(bundle, project_id="run-test", seed_input="seed")
        self.assertEqual("research-selection/v1", current["selection"]["contract_version"])
        self.assertEqual(legacy["selection"], current["selection"])
        self.assertNotIn("intent_sha256", current)

    def test_intent_is_passed_to_selection_and_only_digest_is_exposed(self) -> None:
        raw_intent = "A private phrase only used for this test"
        result = run(self.bundle(), project_id="run-test", seed_input="seed", intent=raw_intent)
        self.assertEqual("research-selection/v2", result["selection"]["contract_version"])
        self.assertEqual("intent-rank/v1", result["intent_algorithm"])
        self.assertEqual(result["intent_sha256"], result["selection"]["intent_sha256"])
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(raw_intent, rendered)
        self.assertNotIn("\"intent\":", rendered)
        for candidate in result["selection"]["selected_candidates"]:
            self.assertIn("intent_score", candidate)
            self.assertIn("intent_kind_scores", candidate)

    def test_cli_digest_matches_selection_and_log_does_not_contain_raw_intent(self) -> None:
        raw_intent = "CLI-only phrase with private wording"
        with tempfile.TemporaryDirectory(prefix="run-intent-test-") as temporary:
            temporary_root = Path(temporary)
            bundle_path = temporary_root / "bundle.json"
            output_path = temporary_root / "run.json"
            bundle_path.write_text(json.dumps(self.bundle(), ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "run.py"),
                    "--bundle",
                    str(bundle_path),
                    "--project-id",
                    "run-test",
                    "--seed-input",
                    "seed",
                    "--intent",
                    raw_intent,
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertNotIn(raw_intent, completed.stdout + completed.stderr)
            summary = json.loads(completed.stdout)
            output = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["intent_sha256"], output["intent_sha256"])
            self.assertEqual(summary["intent_sha256"], output["selection"]["intent_sha256"])
            self.assertEqual("intent-rank/v1", summary["intent_algorithm"])


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

    @staticmethod
    def _write_handoff(root: Path, project_slug: str, handoff_id: str, revision: int, commit: str, generated_at: str) -> None:
        path = root / "projects" / project_slug / "05_production" / "production-handoff.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    f"handoff_id: {handoff_id}",
                    f"revision: {revision}",
                    f"research_commit: {commit}",
                    f"generated_at: '{generated_at}'",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def test_first_handoff_uses_ho001_revision_one(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = MODULE._handoff_arguments(
                Path(temporary), "harmony", "2026-08-20T00:00:00+09:00", "a" * 40
            )

        self.assertEqual(
            [
                "--generated-at", "2026-08-20T00:00:00+09:00",
                "--research-commit", "a" * 40,
                "--handoff-id", "HO001",
                "--revision", "1",
            ],
            args,
        )

    def test_changed_source_allocates_next_handoff_and_supersedes_previous(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_handoff(root, "harmony", "HO009", 9, "a" * 40, "2026-08-19T00:00:00+09:00")
            args = MODULE._handoff_arguments(
                root, "harmony", "2026-08-20T00:00:00+09:00", "b" * 40
            )

        self.assertEqual(
            [
                "--generated-at", "2026-08-20T00:00:00+09:00",
                "--research-commit", "b" * 40,
                "--handoff-id", "HO010",
                "--revision", "10",
                "--supersedes", "HO009",
            ],
            args,
        )

    def test_unchanged_source_reuses_existing_handoff_identity_and_timestamp(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_handoff(root, "harmony", "HO009", 9, "a" * 40, "2026-08-19T00:00:00+09:00")
            args = MODULE._handoff_arguments(
                root, "harmony", "2026-08-20T00:00:00+09:00", "a" * 40
            )

        self.assertEqual(
            [
                "--generated-at", "2026-08-19T00:00:00+09:00",
                "--research-commit", "a" * 40,
                "--handoff-id", "HO009",
                "--revision", "9",
            ],
            args,
        )


class RequestForwardingTests(unittest.TestCase):
    def test_full_run_passes_research_root_to_request_builder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captured: list[list[str]] = []

            def fake_tool(args: list[str], python: str) -> dict:
                captured.append(args)
                if args[0] == "tools/build_research_request.py":
                    output = Path(args[args.index("--output") + 1])
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "RR001.yaml").write_text("request_id: RR001\n", encoding="utf-8")
                return {"status": "PASSED"}

            def fake_child(root_path: Path, args: list[str], python: str, **kwargs) -> dict:
                if args[0] == "tools/complete.py":
                    return {"status": "NOT_READY"}
                return {"status": "PASSED"}

            with patch.object(MODULE, "_materialize_offline_signals", return_value={"status": "PASSED"}), \
                    patch.object(MODULE, "_run_tool", side_effect=fake_tool), \
                    patch.object(MODULE, "_run_child", side_effect=fake_child), \
                    patch.object(MODULE, "_theme_proposal", return_value={"status": "PROPOSED"}):
                report = MODULE._run_orchestration(
                    "調和", root / "workspace", root / "state", "RUN001", "artistic-research",
                    None, None, "2026-08-20T00:00:00+09:00", sys.executable,
                    research_root=root / "research", production_root=root / "production",
                    offline_fixture=True,
                )

            request_calls = [args for args in captured if args[0] == "tools/build_research_request.py"]
            self.assertEqual(1, len(request_calls))
            self.assertEqual(str(root / "research"), request_calls[0][request_calls[0].index("--research-root") + 1])
            self.assertEqual("RESEARCH_PENDING", report["status"])


if __name__ == "__main__":
    unittest.main()
