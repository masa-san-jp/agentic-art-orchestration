"""Stage B -> C -> handoff -> D by elements through run.py's hand-out helpers, with real child checkouts.

Runs only when AAO_CHAIN_RESEARCH_ROOT and AAO_CHAIN_PRODUCTION_ROOT name agentic-art-research and
agentic-art-production checkouts (with their Python dependencies installed for this interpreter).
Both children's fake answerers answer every request; the requests come from run.py's helpers, and
each answer goes to the `answer_command` they hand out, exactly as an agent would send it.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from tools import run as MODULE

RESEARCH = os.environ.get("AAO_CHAIN_RESEARCH_ROOT")
PRODUCTION = os.environ.get("AAO_CHAIN_PRODUCTION_ROOT")
NOW = "2026-10-13T00:00:00Z"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(RESEARCH and PRODUCTION, "set AAO_CHAIN_RESEARCH_ROOT and AAO_CHAIN_PRODUCTION_ROOT")
class StageCDChainTests(unittest.TestCase):
    def answer(self, command: list[str], answer: dict) -> None:
        result = subprocess.run(command, input=json.dumps(answer, ensure_ascii=False), capture_output=True, text=True)
        self.assertIn(result.returncode, (0, 1), result.stderr)

    def drive(self, report_of, fake, mutate=None) -> dict:
        report = report_of()
        for _ in range(400):
            if report.get("status") != "WAITING":
                return report
            request = report["next_action"]["request"]
            answer = fake.answer(request)
            if mutate:
                mutate(request, answer)
            self.answer(report["answer_command"], answer)
            report = report_of()
        self.fail("element run did not finish")

    def test_b_c_d_by_elements_end_to_end(self):
        research, production = Path(RESEARCH).resolve(), Path(PRODUCTION).resolve()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            sys.path.insert(0, str(research / "tools"))
            try:
                from new_project import create_project
                project = create_project(root, "elements", "Elements", protocol_root=research, created_at=NOW)
            finally:
                sys.path.remove(str(research / "tools"))
            (project / "00_intake/creative-intent.md").write_text("How does a deferred choice shape a shared image?")
            plan_path = project / "01_planning/research-plan.yaml"
            plan = yaml.safe_load(plan_path.read_text())
            plan["element_research"] = {"question_count": 1, "search_limit": 2}
            plan["minimums"] = {"evidence": 2, "claims": 2, "insights": 1, "decisions": 1, "requirements": 4,
                                "reason": "Synthetic bounded chain qualification."}
            plan_path.write_text(yaml.safe_dump(plan, sort_keys=False))
            research_fake = load(research / "tests/fixtures/workers/fake_research_answerer.py", "chain_research_fake")
            plan_fake = load(production / "tests/fixtures/plan_elements/fake_answerer.py", "chain_plan_fake")
            python = sys.executable

            def distinct(request, answer):
                # Two decisions adopting different options give two comparable work plans.
                if request["element_id"] == "adopt.DC002":
                    answer["value"] = request["answer_format"]["choices"][-1]
                if request["element_id"] == "difference.EV002.DC002":
                    answer["value"] = "The fixed image in the source differs because the final composition here locks at opening."

            stage_b = self.drive(lambda: MODULE._research_elements(research, project, "CHAIN", python), research_fake, distinct)
            self.assertEqual("COMPLETED", stage_b["status"])
            stage_c = self.drive(lambda: MODULE._work_elements(research, project, "CHAIN", python), research_fake)
            self.assertEqual("COMPLETED", stage_c["status"])
            start = MODULE._stage_d_start(research, project, python)
            self.assertTrue(start["allowed"], start)

            def child(repository: Path, *args: str) -> None:
                result = subprocess.run([python, *args], cwd=repository, capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            roots = ["--work-root", str(root), "--protocol-root", str(research)]
            child(research, "tools/build_handoff.py", "projects/elements", *roots, "--generated-at", NOW,
                  "--research-commit", "a" * 40, "--handoff-id", "HO001", "--revision", "1")
            child(research, "tools/export_handoff.py", "projects/elements", *roots, "--output", str(root / "bundle"),
                  "--allow-dirty")
            output = root / "production-output"
            child(production, "tools/new_production.py", "elements", "--handoff", str(root / "bundle"),
                  "--output-root", str(output))
            production_project = output / "production/elements"
            first = MODULE._plan_elements(production, production_project, "CHAIN", python)
            action = MODULE._element_action("production", str(production_project), first, ["resume"], "FORBIDDEN")
            self.assertEqual(("element", "production", "medium"),
                             (action["kind"], action["stage"], action["request"]["element_id"]))
            stage_d = self.drive(lambda: MODULE._plan_elements(production, production_project, "CHAIN", python), plan_fake)
            self.assertEqual("COMPLETED", stage_d["status"], stage_d)
            self.assertEqual("PLAN_READY", stage_d["completion"]["plan_status"], stage_d["completion"])
            verified = subprocess.run([python, "tools/plan_actionability.py", "--project-root", str(production_project)],
                                      cwd=production, capture_output=True, text=True)
            self.assertEqual("PLAN_READY", json.loads(verified.stdout)["plan_status"])
