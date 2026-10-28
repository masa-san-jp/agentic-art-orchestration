from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import yaml

from tools import public_projection
from tools.input_pipeline import run_input_pipeline
from tools.output_destinations import resolve_destinations
from tools.run import run
from tools.signal_bundle import build_signal_bundle
from tests.test_canonical_plan_projection import write_fake_attestation_tool


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

    def test_profiled_bundle_uses_internal_output_and_records_resolution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="run-destinations-") as temporary:
            root = Path(temporary)
            profile_path = root / "profile.yaml"
            profile_path.write_text(
                yaml.safe_dump({
                    "contract_version": "output-destinations/v1",
                    "profile": "test",
                    "destinations": {
                        "state_root": str(root / "state"),
                        "internal_output_root": str(root / "internal"),
                    },
                }, sort_keys=False),
                encoding="utf-8",
            )
            bundle_path = root / "bundle.json"
            bundle_path.write_text(json.dumps(self.bundle(), ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable, str(ROOT / "tools" / "run.py"),
                    "--bundle", str(bundle_path), "--project-id", "run-test", "--seed-input", "seed",
                    "--run-id", "BUNDLE-RUN", "--destinations-file", str(profile_path),
                ], cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            summary = json.loads(completed.stdout)
            output = root / "internal" / "run" / "run-test" / "run.json"
            evidence = root / "state" / "BUNDLE-RUN" / "destination-resolution.json"
            self.assertTrue(output.is_file())
            self.assertTrue(evidence.is_file())
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("destination-resolution/v1", document["destination_resolution"]["contract_version"])
            self.assertEqual(document["destination_resolution"], summary["destination_resolution"])


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

    def _protocol(self, route: str | None = "research_elements", engine: str | None = None) -> tuple[Path, Path]:
        protocol = self.work / "protocol"
        (protocol / "tools").mkdir(parents=True)
        if engine is not None:
            (protocol / "tools" / "research_elements.py").write_text(engine, encoding="utf-8")
        project = self.work / "projects" / "harmony"
        (project / "01_planning").mkdir(parents=True)
        plan = {"research_route": route} if route else {}
        (project / "01_planning" / "research-plan.yaml").write_text(json.dumps(plan), encoding="utf-8")
        return protocol, project

    def test_element_route_hands_the_agent_one_research_request(self):
        engine = ("import json, sys\n"
                  "assert sys.argv[1:4] == ['next', '--project', sys.argv[3]] and sys.argv[4:] == ['--run-id', 'RUN001-research']\n"
                  "print(json.dumps({'status': 'WAITING', 'accepted_count': 0, 'completion': None,\n"
                  "  'next_action': {'kind': 'element', 'request': {'contract_version': 'element-request/v1', 'element_id': 'question.Q001'}}}))\n")
        protocol, project = self._protocol(engine=engine)

        elements = MODULE._research_elements(protocol, project, "RUN001", sys.executable)
        report = MODULE._at_research(self.work, "RUN001", "調和", [], self.work, "harmony",
                                     resume_command=["resume"], elements=elements)

        action = report["next_action"]
        self.assertEqual("RESEARCH_PENDING", report["status"])
        self.assertEqual(("element", "research"), (action["kind"], action["stage"]))
        self.assertEqual("question.Q001", action["request"]["element_id"])
        self.assertEqual([sys.executable, str(protocol / "tools" / "research_elements.py"), "answer", "--project", str(project)],
                         action["answer_command"])
        self.assertEqual(["resume"], action["resume_command"])

    def test_blocked_element_research_is_reported_as_blocked(self):
        elements = {"status": "BLOCKED", "blocked": {"element_id": "claim.CL001", "last_failure": [{"check": "one_sentence"}]},
                    "next_action": None, "answer_command": ["x"]}
        report = MODULE._at_research(self.work, "RUN001", "調和", [], self.work, "harmony", elements=elements)

        self.assertEqual("BLOCKED", report["status"])
        self.assertEqual("claim.CL001", report["blocked"]["element_id"])

    def test_finished_engine_is_read_not_re_entered(self):
        protocol, project = self._protocol(engine="raise SystemExit('must not run after Stage B finished')\n")
        (project / "07_runtime").mkdir()
        (project / "07_runtime" / "research-elements.json").write_text(json.dumps(
            {"run_id": "RUN001-research", "status": "COMPLETED", "answers": {"a": 1, "b": 2},
             "completion": {"status": "INCOMPLETE"}}), encoding="utf-8")

        elements = MODULE._research_elements(protocol, project, "RUN001", sys.executable)

        self.assertEqual(("COMPLETED", 2), (elements["status"], elements["accepted_count"]))
        report = MODULE._at_research(self.work, "RUN001", "調和", [], self.work, "harmony", elements=elements)
        self.assertEqual("RESEARCH_PENDING", report["status"])
        self.assertIn("段階 C", report["next_action"]["do"][0])

    def test_another_runs_finished_checkpoint_is_not_trusted(self):
        engine = "import json\nprint(json.dumps({'status': 'WAITING', 'next_action': {'kind': 'element', 'request': {}}}))\n"
        protocol, project = self._protocol(engine=engine)
        (project / "07_runtime").mkdir()
        (project / "07_runtime" / "research-elements.json").write_text(json.dumps(
            {"run_id": "other-research", "status": "COMPLETED", "answers": {}}), encoding="utf-8")

        self.assertEqual("WAITING", MODULE._research_elements(protocol, project, "current", sys.executable)["status"])

    def test_parent_run_id_maps_to_the_research_engine_rule(self):
        ids = ["RUN001", "run:001", "run:002", "a:b", "a-b", "R" * 119, "R" * 120, "R" * 128, "a:" * 60]
        children = [MODULE._research_run_id(run_id) for run_id in ids]
        for run_id, child in zip(ids, children):
            self.assertRegex(child, r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
            self.assertEqual(child, MODULE._research_run_id(run_id))
        self.assertEqual(len(ids), len(set(children)))
        self.assertEqual("RUN001-research", children[0])

    def test_stage_c_request_follows_a_completed_stage_b(self):
        protocol, project = self._protocol(engine="raise SystemExit('Stage B is read from its checkpoint')\n")
        (protocol / "tools" / "work_elements.py").write_text(
            "import json, sys\n"
            "assert sys.argv[1:] == ['next', '--project', sys.argv[3], '--run-id', 'RUN001-work'], sys.argv\n"
            "print(json.dumps({'status': 'WAITING', 'accepted_count': 3, 'completion': None,\n"
            "  'next_action': {'kind': 'element', 'request': {'contract_version': 'element-request/v1', 'element_id': 'plan.PH001.title'}}}))\n",
            encoding="utf-8")
        elements = {"status": "COMPLETED", "accepted_count": 159, "completion": {"status": "INCOMPLETE"}}

        work = MODULE._work_elements(protocol, project, "RUN001", sys.executable)
        report = MODULE._at_research(self.work, "RUN001", "調和", [], self.work, "harmony", resume_command=["resume"],
                                     elements=elements, work_elements=work)

        action = report["next_action"]
        self.assertEqual("RESEARCH_PENDING", report["status"])
        self.assertEqual(("element", "work"), (action["kind"], action["stage"]))
        self.assertEqual("plan.PH001.title", action["request"]["element_id"])
        self.assertEqual([sys.executable, str(protocol / "tools" / "work_elements.py"), "answer", "--project", str(project)],
                         action["answer_command"])
        self.assertEqual(["resume"], action["resume_command"])

    def test_stage_d_start_rule_stops_with_its_reasons(self):
        protocol, project = self._protocol()
        (protocol / "tools" / "work_elements.py").write_text(
            "import json, sys\nassert sys.argv[1] == 'stage-d-start'\n"
            "print(json.dumps({'allowed': False, 'reasons': ['MECHANISM_MERELY_PLAINER: revise'], 'rule': 'r'}))\n"
            "raise SystemExit(1)\n", encoding="utf-8")

        start = MODULE._stage_d_start(protocol, project, sys.executable)
        report = MODULE._at_research(self.work, "RUN001", "調和", [], self.work, "harmony",
                                     elements={"status": "COMPLETED"}, work_elements={"status": "COMPLETED"},
                                     stage_d_start=start)

        self.assertEqual(("BLOCKED", "STAGE_D_NOT_READY"), (report["status"], report["stop_reason"]))
        self.assertIn("MECHANISM_MERELY_PLAINER: revise", report["next_action"]["do"])

    def test_stage_d_request_uses_the_same_hand_out(self):
        production = self.work / "production-code"
        (production / "tools").mkdir(parents=True)
        (production / "tools" / "plan_elements.py").write_text(
            "import json, sys\n"
            "assert sys.argv[1:] == ['next', '--project-root', sys.argv[3], '--run-id', 'RUN001-plan'], sys.argv\n"
            "print(json.dumps({'status': 'WAITING', 'accepted_count': 0, 'next_action': {'kind': 'element',\n"
            "  'request': {'contract_version': 'element-request/v1', 'element_id': 'medium'}}}))\n", encoding="utf-8")
        project = self.work / "production" / "harmony"

        report = MODULE._plan_elements(production, project, "RUN001", sys.executable)
        action = MODULE._element_action("production", str(project), report, ["resume"], "FORBIDDEN")

        self.assertEqual(("element", "production", "medium"), (action["kind"], action["stage"], action["request"]["element_id"]))
        self.assertEqual([sys.executable, str(production / "tools" / "plan_elements.py"), "answer", "--project-root", str(project)],
                         action["answer_command"])
        self.assertIsNone(MODULE._plan_elements(self.work / "old", project, "RUN001", sys.executable))

    def test_child_stage_ids_follow_the_research_id_rule(self):
        for run_id in ("RUN001", "a:b", "R" * 128):
            for stage in ("work", "plan"):
                child = MODULE._child_run_id(run_id, stage)
                self.assertRegex(child, r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
                self.assertTrue(child.endswith("-" + stage))
        self.assertEqual("RUN001-work", MODULE._child_run_id("RUN001", "work"))

    def test_legacy_route_or_old_research_checkout_keeps_the_task_instructions(self):
        protocol, project = self._protocol(route="legacy", engine="raise SystemExit('must not run')\n")
        self.assertIsNone(MODULE._research_elements(protocol, project, "RUN001", sys.executable))
        old = self.work / "old-protocol"
        (old / "tools").mkdir(parents=True)
        self.assertIsNone(MODULE._research_elements(old, project, "RUN001", sys.executable))


class HandoverArgumentTests(unittest.TestCase):
    def test_completed_research_project_is_promoted_before_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "projects" / "harmony"
            project.mkdir(parents=True)
            manifest = {
                "project": {"id": "project/harmony", "status": "COMPLETE"},
                "entry_points": {},
            }
            (project / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
            MODULE._promote_research_handoff(root, "harmony")
            updated = yaml.safe_load((project / "manifest.yaml").read_text(encoding="utf-8"))

        self.assertEqual("PRODUCTION_HANDOFF", updated["workflow_mode"])
        self.assertEqual("05_production/production-handoff.yaml", updated["entry_points"]["production_handoff"])

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

    def test_empty_template_handoff_is_generated_as_first_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_handoff(root, "harmony", "HO000", 0, "0" * 40, "")
            path = root / "projects" / "harmony" / "05_production" / "production-handoff.yaml"
            path.write_text("{}\n", encoding="utf-8")
            args = MODULE._handoff_arguments(root, "harmony", "2026-08-20T00:00:00+09:00", "a" * 40)

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
    def test_self_hearing_step_is_metadata_only_and_does_not_change_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            hearing = state / "RUN-HEARING" / "hearing.json"
            hearing.parent.mkdir(parents=True)
            hearing.write_text(json.dumps({
                "contract_version": "self-hearing-outcome/v1",
                "run_id": "RUN-HEARING",
                "outcome": "answered",
                "reason": None,
                "question_id": "avoidance",
                "ts": "2026-09-20T00:00:00Z",
            }), encoding="utf-8")

            def fake_tool(args: list[str], python: str) -> dict:
                if args[0] == "tools/build_research_request.py":
                    output = Path(args[args.index("--output") + 1])
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "RR001.yaml").write_text(
                        "request_id: RR001\nintent:\n  creative_question: derived\n", encoding="utf-8",
                    )
                return {"status": "PASSED"}

            with patch.object(MODULE, "_materialize_offline_signals", return_value={"status": "PASSED"}), \
                    patch.object(MODULE, "_run_tool", side_effect=fake_tool), \
                    patch.object(MODULE, "_theme_proposal", return_value={"status": "PROPOSED"}), \
                    patch.object(MODULE, "observe_git_write_credentials", return_value="absent"):
                report = MODULE._run_orchestration(
                    None, root / "workspace", state, "RUN-HEARING", "artistic-research",
                    None, None, "2026-09-20T00:00:00+00:00", sys.executable, offline_fixture=True,
                )

            hearing_step = next(step for step in report["steps"] if step["step"] == "self-hearing")
            self.assertEqual("answered", hearing_step["status"])
            self.assertIsNone(hearing_step["reason"])
            self.assertEqual("AT_EDGE", report["status"])
            self.assertEqual("INCOMPLETE", report["delivery_completion"]["status"])

    def test_run_does_not_project_packet_or_answer_strings_from_hearing_record(self):
        packet_secret = "PACKET-SECRET-DO-NOT-PUBLISH"
        answer_secret = "ANSWER-SECRET-DO-NOT-PUBLISH"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            work = state / "RUN-REDACT"
            work.mkdir(parents=True)
            (work / "hearing.json").write_text(json.dumps({
                "contract_version": "self-hearing-outcome/v1",
                "run_id": "RUN-REDACT",
                "outcome": "offered",
                "reason": "bad reason with spaces",
                "question_id": "../../outside",
                "intent": [packet_secret],
                "question": packet_secret,
                "anchors": [packet_secret],
                "answer": answer_secret,
            }), encoding="utf-8")
            for filename in ("state.yaml", "handoff.md", "hearing.log"):
                (work / filename).write_text("metadata-only\n", encoding="utf-8")

            def fake_tool(args: list[str], python: str) -> dict:
                if args[0] == "tools/build_research_request.py":
                    output = Path(args[args.index("--output") + 1])
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "RR001.yaml").write_text(
                        "request_id: RR001\nintent:\n  creative_question: derived\n", encoding="utf-8",
                    )
                return {"status": "PASSED"}

            with patch.object(MODULE, "_materialize_offline_signals", return_value={"status": "PASSED"}), \
                    patch.object(MODULE, "_run_tool", side_effect=fake_tool), \
                    patch.object(MODULE, "_theme_proposal", return_value={"status": "PROPOSED"}), \
                    patch.object(MODULE, "observe_git_write_credentials", return_value="absent"):
                report = MODULE._run_orchestration(
                    None, root / "workspace", state, "RUN-REDACT", "artistic-research",
                    None, None, "2026-09-20T00:00:00+00:00", sys.executable, offline_fixture=True,
                )

            step = next(item for item in report["steps"] if item["step"] == "self-hearing")
            self.assertEqual({"step": "self-hearing", "status": "unavailable", "reason": "HEARING_UNAVAILABLE"}, step)
            for filename in ("run.json", "state.yaml", "handoff.md", "hearing.log"):
                text = (work / filename).read_text(encoding="utf-8")
                self.assertNotIn(packet_secret, text)
                self.assertNotIn(answer_secret, text)

    def test_real_run_missing_profile_blocks_before_state_or_child_invocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            with patch.object(MODULE, "_guard_pinned_workspace", return_value={"status": "PASSED"}), \
                    patch.object(MODULE, "_run_tool") as tool, \
                    patch.object(MODULE, "_run_child") as child:
                with self.assertRaisesRegex(MODULE.BlockedPrecondition, "PROFILE_ROOT_REQUIRED"):
                    MODULE._run_orchestration(
                        None, root / "workspace", state, "PROFILE-MISSING", "artistic-research",
                        None, None, "2026-09-06T00:00:00+00:00", sys.executable,
                    )
            tool.assert_not_called()
            child.assert_not_called()
            self.assertFalse(state.exists())

    def test_public_cli_passes_explicit_profile_to_the_ingest_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "外部 profile $(not-a-command)"
            stderr = io.StringIO()
            with patch.object(MODULE, "_guard_pinned_workspace", return_value={"status": "PASSED"}), \
                    patch.object(MODULE, "_run_tool", side_effect=MODULE.StepFailure("boundary probe")) as tool, \
                    redirect_stderr(stderr):
                code = MODULE.main([
                    "--workspace-root", str(root / "workspace"),
                    "--state-root", str(root / "state"),
                    "--profile-root", str(profile), "--run-id", "PROFILE-FORWARD",
                ])
            self.assertEqual(1, code)
            self.assertEqual("boundary probe", json.loads(stderr.getvalue())["detail"])
            self.assertEqual(1, tool.call_count)
            args = tool.call_args.args[0]
            self.assertEqual("tools/ingest_signals.py", args[0])
            self.assertEqual(str(profile), args[args.index("--profile-root") + 1])

    def test_offline_cli_ignores_unavailable_profile_and_real_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stdout = io.StringIO()
            with patch.object(MODULE, "_guard_pinned_workspace") as guard, redirect_stdout(stdout):
                code = MODULE.main([
                    "--offline-fixture", "--workspace-root", str(root / "missing"),
                    "--profile-root", "relative-profile-that-must-not-be-read",
                    "--state-root", str(root / "state"), "--run-id", "PROFILE-OFFLINE",
                ])
            self.assertEqual(0, code, stdout.getvalue())
            guard.assert_not_called()
            report = json.loads(stdout.getvalue())
            self.assertEqual("AT_EDGE", report["status"])
            self.assertEqual("OFFLINE_FIXTURE", report["steps"][0]["mode"])
            self.assertTrue((root / "state/PROFILE-OFFLINE/requests").is_dir())
            self.assertNotIn("profile-root", stdout.getvalue())

    def test_full_run_passes_research_root_to_request_builder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captured: list[list[str]] = []
            child_captured: list[list[str]] = []

            def fake_tool(args: list[str], python: str) -> dict:
                captured.append(args)
                if args[0] == "tools/build_research_request.py":
                    output = Path(args[args.index("--output") + 1])
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "RR001.yaml").write_text("request_id: RR001\n", encoding="utf-8")
                return {"status": "PASSED"}

            def fake_child(root_path: Path, args: list[str], python: str, **kwargs) -> dict:
                child_captured.append(args)
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
                    research_work_root=(root / "research-work").resolve(), offline_fixture=True,
                )

            request_calls = [args for args in captured if args[0] == "tools/build_research_request.py"]
            self.assertEqual(1, len(request_calls))
            self.assertEqual(str(root / "research"), request_calls[0][request_calls[0].index("--research-root") + 1])
            self.assertTrue(any(args[0] == "tools/accept_research_request.py" and args[args.index("--protocol-root") + 1] == str(root / "research") for args in child_captured))
            self.assertTrue(any(args[0] == "tools/complete.py" and args[args.index("--protocol-root") + 1] == str(root / "research") for args in child_captured))
            self.assertEqual("RESEARCH_PENDING", report["status"])


class ProductionHistoryTests(unittest.TestCase):
    def _run_prototype_fixture(self, prototype_outcome: dict, *, element_checkpoint=False, completed_work=False) -> tuple[dict, list[list[str]], object]:
        self.temporary = tempfile.TemporaryDirectory(prefix="run-prototype-stage-")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        captured: list[list[str]] = []
        if element_checkpoint:
            checkpoint = root / "state/research-work/projects/run-plan/07_runtime/research-elements.json"
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text('{}')

        def fake_tool(args: list[str], python: str) -> dict:
            if args[0] == "tools/build_research_request.py":
                output = Path(args[args.index("--output") + 1])
                output.mkdir(parents=True, exist_ok=True)
                (output / "RR001.yaml").write_text(
                    "request_id: RR001\nintent:\n  creative_question: derived\n", encoding="utf-8",
                )
            return {"status": "PASSED"}

        def fake_child(root_path: Path, args: list[str], python: str, **kwargs) -> dict:
            captured.append(args)
            if args[0] == "tools/complete.py":
                return {"status": "COMPLETE"}
            if args[0] == "tools/new_production.py":
                project = Path(args[args.index("--output-root") + 1]) / "production" / "run-plan"
                (project / "05_execution").mkdir(parents=True, exist_ok=True)
                (project / "05_execution" / "output-versions.yaml").write_text("version: 1\n", encoding="utf-8")
            if args[0] == "tools/build_plan.py":
                project = Path(args[args.index("--project-root") + 1])
                (project / "03_plan").mkdir(parents=True, exist_ok=True)
                (project / "03_plan" / "production-plan.md").write_text("# plan\n", encoding="utf-8")
            if args[0] == "tools/build_prototype.py":
                return prototype_outcome
            return {"status": "PASSED"}

        with patch.object(MODULE, "_materialize_offline_signals", return_value={"status": "PASSED"}), \
                patch.object(MODULE, "_run_tool", side_effect=fake_tool), \
                patch.object(MODULE, "_run_child", side_effect=fake_child), \
                patch.object(MODULE, "_theme_proposal", return_value={"status": "PROPOSED"}), \
                patch.object(MODULE, "verify_plan", return_value={
                    "plan_status": "PLAN_READY",
                    "owner_verification": {"plan_status": "PLAN_READY"},
                }), \
                patch.object(MODULE, "_handoff_arguments", return_value=[
                    "--generated-at", "2026-08-20T00:00:00+09:00", "--research-commit", "a" * 40,
                    "--handoff-id", "HO001", "--revision", "1",
                ]), \
                patch.object(MODULE, "_head", return_value="d" * 40), \
                patch.object(MODULE, "_research_elements", return_value={"status": "COMPLETED"}), \
                patch.object(MODULE, "_work_elements", return_value={
                    "status": "COMPLETED" if completed_work else "WAITING", "accepted_count": 0, "completion": None,
                    "next_action": {"request": {"element_id": "plan.PH001.title"}},
                    "answer_command": ["work-answer"],
                }), \
                patch.object(MODULE, "_stage_d_start", return_value={"allowed": True, "reasons": []}), \
                patch.object(MODULE, "_plan_elements", return_value={
                    "status": "WAITING", "accepted_count": 0, "abandoned": [],
                    "next_action": {"request": {"element_id": "medium"}}, "answer_command": ["plan-answer"],
                }):
            report = MODULE._run_orchestration(
                "調和", root / "workspace", root / "state", "RUN-PROTOTYPE", "artistic-research",
                "run-plan", "Run plan", "2026-08-20T00:00:00+09:00", sys.executable,
                research_root=root / "research", production_root=root / "production", offline_fixture=True,
            )
        return report, captured, root

    def test_checkpoint_route_uses_stage_c_without_mutating_native_completion(self):
        report, captured, _ = self._run_prototype_fixture({"status": "PASSED"}, element_checkpoint=True)
        self.assertNotIn("tools/complete.py", [args[0] for args in captured])
        self.assertNotIn("tools/build_plan.py", [args[0] for args in captured])
        self.assertEqual(("element", "work"), (report['next_action']['kind'], report['next_action']['stage']))

    def test_completed_stage_c_returns_stage_d_through_the_run_entry(self):
        report, captured, _ = self._run_prototype_fixture(
            {"status": "PASSED"}, element_checkpoint=True, completed_work=True)
        self.assertNotIn("tools/complete.py", [args[0] for args in captured])
        self.assertNotIn("tools/build_plan.py", [args[0] for args in captured])
        self.assertEqual(("element", "production", "medium"),
                         (report['next_action']['kind'], report['next_action']['stage'],
                          report['next_action']['request']['element_id']))

    def test_normal_run_executes_prototype_before_owner_verification(self):
        report, captured, _ = self._run_prototype_fixture({"status": "PASSED"})
        stages = [args[0] for args in captured]
        self.assertLess(stages.index("tools/build_plan.py"), stages.index("tools/build_prototype.py"))
        self.assertIn("prototype", [step["step"] for step in report["steps"]])
        self.assertNotIn("PROTOTYPE_OUTPUT", report["delivery_completion"]["missing"])

    def test_normal_run_persists_repairable_prototype_failure(self):
        report, captured, root = self._run_prototype_fixture({
            "status": "NOT_READY", "detail": "PROTOTYPE_RENDER_INPUTS",
        })
        self.assertEqual("AT_PRODUCTION", report["status"])
        self.assertEqual("INCOMPLETE", report["delivery_completion"]["status"])
        self.assertEqual("prototype", report["next_action"]["stage"])
        self.assertIn("--project-root", report["next_action"]["prototype_command"])
        self.assertIn("--project-root", report["next_action"]["validation_command"])
        self.assertEqual("PROTOTYPE_RENDER_INPUTS", report["steps"][-1]["detail"])
        self.assertTrue((root / "state/RUN-PROTOTYPE/run.json").is_file())

    def test_production_root_is_stable_when_run_id_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_root = Path(temporary) / "state"

            self.assertEqual(state_root.resolve() / "production", MODULE._production_output_root(state_root))

    def test_run_to_project_history_is_append_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_root = Path(temporary) / "state"
            history = MODULE._record_production_run(
                state_root, "RUN001", "harmony", "2026-08-20T00:00:00+09:00"
            )
            MODULE._record_production_run(
                state_root, "RUN001", "harmony", "2026-08-21T00:00:00+09:00"
            )
            MODULE._record_production_run(
                state_root, "RUN002", "harmony", "2026-08-21T00:00:00+09:00"
            )

            entries = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(2, len(entries))
        self.assertEqual(["RUN001", "RUN002"], [entry["run_id"] for entry in entries])
        self.assertEqual({"production/harmony"}, {entry["project_id"] for entry in entries})
        self.assertEqual({"MATERIALIZED"}, {entry["status"] for entry in entries})

    def test_changed_handoff_retries_through_revision_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            bundle.mkdir()
            outcomes = [
                {"status": "NOT_READY", "detail": "PROJECT_IDEMPOTENCY_MISMATCH: supersedes required"},
                {"status": "PASSED"},
            ]

            with patch.object(MODULE, "_run_child", side_effect=outcomes) as child:
                outcome, mode = MODULE._production_acceptance(
                    root / "production-repository",
                    root / "persistent-production",
                    bundle,
                    "harmony",
                    "2026-08-20T00:00:00+09:00",
                    "RUN002",
                    sys.executable,
                )

            retry_args = child.call_args_list[1].args[1]

        self.assertEqual("PASSED", outcome["status"])
        self.assertEqual("ACCEPT_REVISION", mode)
        self.assertEqual(str(root / "persistent-production"), retry_args[retry_args.index("--output-root") + 1])
        self.assertIn("--accept-revision", retry_args)
        self.assertEqual("RUN002/production/harmony", retry_args[retry_args.index("--idempotency-key") + 1])

    def test_two_run_ids_share_production_records_and_second_plan_sees_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_root = root / "state"
            (root / "research").mkdir()
            captured: list[dict] = []

            def fake_tool(args: list[str], python: str) -> dict:
                if args[0] == "tools/build_research_request.py":
                    output = Path(args[args.index("--output") + 1])
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "RR001.yaml").write_text(
                        "request_id: RR001\nintent:\n  creative_question: derived\n",
                        encoding="utf-8",
                    )
                return {"status": "PASSED"}

            def fake_child(root_path: Path, args: list[str], python: str, **kwargs) -> dict:
                if args[0] == "tools/complete.py":
                    return {"status": "COMPLETE"}
                if args[0] == "tools/new_production.py":
                    output_root = Path(args[args.index("--output-root") + 1])
                    project = output_root / "production" / "harmony"
                    previously_materialized = (project / "05_execution" / "output-versions.yaml").is_file()
                    ledger = project / "05_execution" / "output-versions.yaml"
                    ledger.parent.mkdir(parents=True, exist_ok=True)
                    ledger.write_text("version: 1\n", encoding="utf-8")
                    captured.append({"step": "accept", "previously_materialized": previously_materialized,
                                     "output_root": output_root})
                elif args[0] == "tools/build_plan.py":
                    project = Path(args[args.index("--project-root") + 1])
                    captured.append({"step": "plan", "prior_records_visible":
                                     (project / "05_execution" / "output-versions.yaml").is_file()})
                return {"status": "PASSED"}

            with patch.object(MODULE, "_materialize_offline_signals", return_value={"status": "PASSED"}), \
                    patch.object(MODULE, "_run_tool", side_effect=fake_tool), \
                    patch.object(MODULE, "_run_child", side_effect=fake_child), \
                    patch.object(MODULE, "_theme_proposal", return_value={"status": "PROPOSED"}), \
                    patch.object(MODULE, "verify_plan", return_value={"plan_status": "PLAN_READY"}), \
                    patch.object(MODULE, "_handoff_arguments", return_value=[
                        "--generated-at", "2026-08-20T00:00:00+09:00",
                        "--research-commit", "a" * 40,
                        "--handoff-id", "HO001", "--revision", "1",
                    ]):
                first = MODULE._run_orchestration(
                    "調和", root / "workspace", state_root, "RUN001", "artistic-research",
                    "harmony", "調和", "2026-08-20T00:00:00+09:00", sys.executable,
                    research_root=root / "research", production_root=root / "production",
                    offline_fixture=True,
                )
                second = MODULE._run_orchestration(
                    "調和", root / "workspace", state_root, "RUN002", "artistic-research",
                    "harmony", "調和", "2026-08-21T00:00:00+09:00", sys.executable,
                    research_root=root / "research", production_root=root / "production",
                    offline_fixture=True,
                )

            entries = [json.loads(line) for line in
                       (state_root / "production-history.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual("PLAN_READY", first["status"])
        self.assertEqual("PLAN_READY", second["status"])
        self.assertEqual(first["production_root"], second["production_root"])
        self.assertEqual(first["plan"], second["plan"])
        self.assertEqual(["RUN001", "RUN002"], [entry["run_id"] for entry in entries])
        accepts = [item for item in captured if item["step"] == "accept"]
        plans = [item for item in captured if item["step"] == "plan"]
        self.assertEqual([False, True], [item["previously_materialized"] for item in accepts])
        self.assertEqual([True, True], [item["prior_records_visible"] for item in plans])

    def _profiled_plan_ready(self, root: Path, run_id: str = "RUN-PROJECTION-001", *, runs: int = 1) -> list[dict]:
        """Reach PLAN_READY with fake workers and a fake Production attestation CLI."""
        write_fake_attestation_tool(root / "production")
        target = root / "public-target"
        if not target.exists():
            subprocess.run(["git", "init", "-q", "-b", "main", str(target)], check=True, capture_output=True)
            public_projection.init_target(target, apply=True)
            subprocess.run(["git", "-C", str(target), "add", "public-project.yaml", "README.md", "plans", "works"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(target), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "scaffold"], check=True, capture_output=True)
            profile = root / "destinations.yaml"
            profile.write_text(yaml.safe_dump({
                "contract_version": "output-destinations/v1",
                "profile": "run-prepare-test",
                "destinations": {
                    "state_root": str(root / "state"),
                    "internal_output_root": str(root / "internal"),
                    "public_projection_root": str(target),
                },
            }, sort_keys=False), encoding="utf-8")
        resolution = resolve_destinations(root / "destinations.yaml", repository_root=ROOT, run_id=run_id)

        def fake_tool(args: list[str], python: str) -> dict:
            if args[0] == "tools/build_research_request.py":
                output = Path(args[args.index("--output") + 1])
                output.mkdir(parents=True, exist_ok=True)
                (output / "RR001.yaml").write_text(
                    "request_id: RR001\nintent:\n  creative_question: derived\n", encoding="utf-8",
                )
            return {"status": "PASSED"}

        def fake_child(root_path: Path, args: list[str], python: str, **kwargs) -> dict:
            if args[0] == "tools/complete.py":
                return {"status": "COMPLETE"}
            if args[0] == "tools/new_production.py":
                project = Path(args[args.index("--output-root") + 1]) / "production" / "run-plan"
                (project / "05_execution").mkdir(parents=True, exist_ok=True)
                (project / "05_execution" / "output-versions.yaml").write_text("version: 1\n", encoding="utf-8")
            if args[0] == "tools/build_plan.py":
                project = Path(args[args.index("--project-root") + 1])
                (project / "03_plan").mkdir(parents=True, exist_ok=True)
                (project / "03_plan" / "production-plan.md").write_text("# plan\n", encoding="utf-8")
            return {"status": "PASSED"}

        reports = []
        with patch.object(MODULE, "_materialize_offline_signals", return_value={"status": "PASSED"}), \
                patch.object(MODULE, "_run_tool", side_effect=fake_tool), \
                patch.object(MODULE, "_run_child", side_effect=fake_child), \
                patch.object(MODULE, "_theme_proposal", return_value={"status": "PROPOSED"}), \
                patch.object(MODULE, "verify_plan", return_value={"plan_status": "PLAN_READY"}), \
                patch.object(MODULE, "_head", return_value="d" * 40):
            for attempt in range(runs):
                # A resumed run gets a new clock; the attestation must not collide.
                reports.append(MODULE._run_orchestration(
                    "調和", root / "workspace", root / "state", run_id, "artistic-research",
                    "run-plan", "Run plan", f"2026-09-04T00:0{attempt}:00+09:00", sys.executable,
                    research_root=root / "research", production_root=root / "production",
                    offline_fixture=True, destination_resolution=resolution,
                    internal_output_root=root / "internal",
                ))
        return reports

    @staticmethod
    def _attestation_calls(root: Path) -> list[list[str]]:
        log = root / "production" / "calls.jsonl"
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    def test_profiled_plan_ready_run_attests_then_invokes_the_single_public_candidate_producer(self):
        with tempfile.TemporaryDirectory(prefix="run-public-prepare-") as temporary:
            root = Path(temporary)
            target = root / "public-target"
            report, = self._profiled_plan_ready(root)

            # The closed automatic lane ran with the pinned Production commit
            # before source_fields read the attestation it wrote.
            calls = self._attestation_calls(root)
            self.assertEqual(1, len(calls))
            self.assertIn("--automatic-plan", calls[0])
            self.assertNotIn("--native-review", calls[0])
            self.assertEqual("d" * 40, calls[0][calls[0].index("--producer-commit") + 1])
            self.assertEqual("2026-09-04T00:00:00+09:00", calls[0][calls[0].index("--generated-at") + 1])
            self.assertEqual("ATTESTED", report["automatic_plan_attestation"]["status"])
            self.assertTrue(report["public_plan_attestation"].endswith("03_plan/public-plan-attestation.json"))
            self.assertEqual("PLAN_READY", report["status"])
            self.assertEqual("BLOCKED_POLICY", report["projection_status"])
            self.assertEqual("automatic-plan-projection-authority/v1", report["automatic_plan_authority"]["contract_version"])
            self.assertEqual("tools/run.py", report["automatic_plan_authority"]["producer"])
            self.assertEqual("BLOCKED_POLICY", report["public_projection"]["status"])
            self.assertEqual("AUTOMATIC_PLAN", report["public_projection"]["projection_mode"])
            # A fake attestation CLI is not the qualified owner checkout.
            self.assertIsNone(report["public_projection"]["request_locator"])
            self.assertFalse((target / "plans/P0001-run-plan/plan.md").exists())
            self.assertTrue(Path(report["plan"]).is_file())
            evidence = root / "state" / "RUN-PROJECTION-001" / "public-projection-result.json"
            self.assertTrue(evidence.is_file())
            result = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual("AUTOMATIC_PLAN", result["projection_mode"])
            self.assertIn("reason: ", result["findings"][0]["remediation"])
            # A blocked projection after PLAN_READY names what to repair.
            action = report["next_action"]
            self.assertEqual(("agent", "projection"), (action["actor"], action["stage"]))
            self.assertEqual("RUN-PROJECTION-001/public-projection-result.json", action["result_locator"])
            self.assertEqual(report["public_projection"]["finding_codes"], action["finding_codes"])
            self.assertIn("--run-id", action["resume_command"])
            self.assertEqual("PUBLIC_PROJECTION_PENDING", report["stop_reason"])

    def test_rejected_automatic_attestation_blocks_before_projection(self):
        with tempfile.TemporaryDirectory(prefix="run-attest-reject-") as temporary:
            root = Path(temporary)
            write_fake_attestation_tool(root / "production")
            (root / "production" / "reject").write_text("PUBLIC_URL_BLOCKED\n", encoding="utf-8")
            report, = self._profiled_plan_ready(root, "RUN-ATTEST-REJECT")

            self.assertEqual("PLAN_READY", report["plan_status"])
            self.assertEqual("BLOCKED", report["projection_status"])
            self.assertEqual("PRODUCTION_AUTOMATIC_ATTESTATION_FAILED", report["stop_reason"])
            finding = {"status": "REJECTED", "reason": "PUBLIC_URL_BLOCKED"}
            self.assertEqual(finding, report["automatic_plan_attestation"]["finding"])
            action = report["next_action"]
            self.assertEqual(("agent", "attestation"), (action["actor"], action["stage"]))
            self.assertEqual(finding, action["finding"])
            self.assertIn("--automatic-plan", action["command"])
            self.assertIn("--run-id", action["resume_command"])
            self.assertNotIn("public_projection", report)
            self.assertFalse((root / "state" / "RUN-ATTEST-REJECT" / "public-projection-result.json").exists())
            self.assertFalse((root / "public-target" / "plans/P0001-run-plan").exists())

    def test_resume_reuses_a_verified_attestation_for_identical_plan_bytes(self):
        with tempfile.TemporaryDirectory(prefix="run-attest-resume-") as temporary:
            root = Path(temporary)
            first, second = self._profiled_plan_ready(root, "RUN-ATTEST-RESUME", runs=2)

            calls = self._attestation_calls(root)
            self.assertEqual(1, sum("--automatic-plan" in call for call in calls))
            self.assertEqual(1, sum("--check" in call for call in calls))
            self.assertEqual("ATTESTED", first["automatic_plan_attestation"]["status"])
            self.assertEqual("ALREADY_ATTESTED", second["automatic_plan_attestation"]["status"])
            self.assertEqual(first["public_plan_attestation_sha256"], second["public_plan_attestation_sha256"])

    @staticmethod
    def _fake_project(root: Path, *, valid: bool) -> Path:
        """A Project checkout whose native generator writes one derived file and whose validator checks it."""
        target = root / "project"
        (target / "tools").mkdir(parents=True)
        (target / "plans").mkdir()
        (target / "tools" / "__init__.py").write_text("", encoding="utf-8")
        (target / "tools" / "catalog_sync.py").write_text(
            "def expected_files(root):\n    return {root / 'plans' / 'lineage-index.json': '{}\\n'}\n", encoding="utf-8")
        check = "sys.exit(0 if (root / 'plans/lineage-index.json').exists() else 1)" if valid else \
            "print('ERROR: plans/index.yaml: indexed plan directories differ'); sys.exit(1)"
        (target / "tools" / "validate.py").write_text(
            "import sys\nfrom pathlib import Path\nroot = Path(sys.argv[sys.argv.index('--root') + 1])\n" + check + "\n",
            encoding="utf-8")
        return target

    def test_projected_catalog_is_regenerated_by_the_project_and_validated(self):
        with tempfile.TemporaryDirectory(prefix="run-catalog-sync-") as temporary:
            target = self._fake_project(Path(temporary), valid=True)
            self.assertEqual({"status": "PASSED"}, MODULE._sync_public_catalog(target, sys.executable))
            self.assertEqual("{}\n", (target / "plans" / "lineage-index.json").read_text(encoding="utf-8"))

    def test_invalid_projected_catalog_is_reported_with_the_validator_lines(self):
        with tempfile.TemporaryDirectory(prefix="run-catalog-invalid-") as temporary:
            target = self._fake_project(Path(temporary), valid=False)
            result = MODULE._sync_public_catalog(target, sys.executable)
            self.assertEqual(("FAILED", "validate"), (result["status"], result["step"]))
            self.assertEqual(["ERROR: plans/index.yaml: indexed plan directories differ"], result["findings"])


if __name__ == "__main__":
    unittest.main()
