#!/usr/bin/env python3
"""Carry one intent as far as the repositories can take it, without asking anyone.

    python3 tools/run.py --intent "調和" --workspace-root <実クローン> --run-id RUN001

The human appears once, in the interaction that produces the intent. From there
the agent driving this repository runs to the edge of what the repositories can
do on their own, and is told what to do next in the same breath. Nothing here
waits for approval: a step either runs, or it names the work that has to happen
and where its result goes.

Steps that are mechanical are executed. The step that needs an agent to read,
search, and write records is returned as an instruction with its acceptance
condition, so the agent can do it and call this again.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "data/runs"


class StepFailure(RuntimeError):
    """A mechanical step failed, so the run cannot continue past it."""


def _run_tool(args: list[str], python: str) -> dict:
    result = subprocess.run([python, *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
        raise StepFailure(f"{args[0]} failed: {detail[0]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"stdout": result.stdout.strip()}


def run(intent: str, workspace_root: Path, state_root: Path, run_id: str, purpose: str,
        slug: str, title: str, requested_at: str, python: str) -> dict:
    """Execute every step the repositories can do alone, in order, and record each one."""
    work = state_root / run_id
    work.mkdir(parents=True, exist_ok=True)
    signals = work / "signals"
    steps: list[dict] = []

    def record(name: str, detail: dict) -> None:
        steps.append({"step": name, **detail})

    record("ingest", _run_tool([
        "tools/ingest_signals.py", "--purpose", purpose,
        "--workspace-root", str(workspace_root), "--output", str(signals),
    ], python))

    record("candidates", _run_tool([
        "tools/candidate_space.py", "--fixture", str(signals), "--output", str(work / "candidates.json"),
    ], python))

    record("gates", _run_tool([
        "tools/candidate_gates.py", "--candidates", str(work / "candidates.json"),
        "--fixture", str(signals), "--output", str(work / "gates.json"),
    ], python))

    record("selection", _run_tool([
        "tools/candidate_selection.py", "--candidates", str(work / "candidates.json"),
        "--fixture", str(signals), "--project-id", slug, "--output", str(work / "selection.json"),
    ], python))

    record("propositions", _run_tool([
        "tools/proposition_provenance.py", "--selection", str(work / "selection.json"),
        "--candidates", str(work / "candidates.json"), "--gates", str(work / "gates.json"),
        "--fixture", str(signals), "--output", str(work / "propositions.json"),
    ], python))

    record("research-request", _run_tool([
        "tools/build_research_request.py", "--propositions", str(work / "propositions.json"),
        "--signals", str(signals), "--slug", slug, "--title", title,
        "--requested-at", requested_at, "--output", str(work / "requests"),
    ], python))

    request = sorted((work / "requests").glob("RR*.yaml"))[-1]

    # The repositories stop here on their own. Conducting the research is not a
    # missing tool: it is reading, searching, and writing records, which the agent
    # driving this repository does. Say what it is and how it is judged done.
    next_action = {
        "actor": "agent",
        "why": "この先は、証拠を取り、主張を書き、先行作品を調べ、棄却案を残す作業で、"
               "道具の実行ではない。ここから先はエージェントが行う。",
        "do": [
            f"研究リポジトリで `python3 tools/accept_research_request.py {request} --apply --root <research>` を実行し、"
            "プロジェクトを作る",
            "作られたプロジェクトの 01_planning/research-plan.yaml のタスクを順に進める",
            "02_evidence に証拠を集める。03_knowledge に観察・主張・関係・矛盾を書く",
            "04_decisions に判断・棄却案・不確実性を書く",
            "05_production に要件・受入試験・試作計画・創作指針を書く",
        ],
        "acceptance": "研究リポジトリで `python3 tools/complete.py <project>` が COMPLETE を返し、"
                      "`python3 tools/build_handoff.py <project> ...` が通ること",
        "then": "`python3 tools/export_handoff.py` で束を出し、制作リポジトリの `tools/new_production.py` と "
                "`tools/build_plan.py` を実行すると制作プランが出る",
        "request": str(request),
    }

    report = {
        "run_id": run_id,
        "intent": intent,
        "status": "AT_EDGE",
        "steps": steps,
        "next_action": next_action,
        "state": str(work),
    }
    (work / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", required=True, help="入力段の対話で人間から受け取ったもの")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--requested-at", required=True)
    parser.add_argument("--purpose", default="artistic-research")
    parser.add_argument("--workspace-root", type=Path, default=ROOT / "repos")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--child-python", default=sys.executable)
    args = parser.parse_args(argv)

    try:
        report = run(args.intent, args.workspace_root, args.state_root, args.run_id,
                     args.purpose, args.slug, args.title, args.requested_at, args.child_python)
    except (StepFailure, OSError, IndexError) as exc:
        print(json.dumps({"status": "FAILED", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
