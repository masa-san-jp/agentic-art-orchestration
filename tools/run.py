#!/usr/bin/env python3
"""Carry one intent all the way to a production plan, without asking anyone.

    python3 tools/run.py --intent "調和" --workspace-root <実クローン> --run-id RUN001

The human appears once, in the interaction that produces the intent. Everything
after that runs without asking: ingest, compose, gate, select, trace, request,
accept, hand over, and build the plan.

One step is not a tool call. Conducting the research means reading, searching,
and writing records, and the agent driving this repository does it. When the
research is not yet done the run returns what is left and how it is judged
done; calling the same entry again with the same run id carries on to the plan.
It waits for the agent, never for a person.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_STATE = ROOT / "data/runs"
DEFAULT_RULES_PATH = ROOT / "config/transformation-rules.yaml"
DEFAULT_OUTPUT_PATH = ROOT / "data/run.json"
HUMAN_OPERATIONS = [
    "merge",
    "release",
    "public_share",
    "consent_expansion",
    "destructive_git",
    "external_cost_over_declared_budget",
    "physical_action",
]


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


def _head(root: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "0" * 40


def _run_child(root: Path, args: list[str], python: str, *, allow_conflict: bool = False,
               allow_failure: bool = False) -> dict:
    """Run a child repository's tool. Already-done steps are not failures on a resume."""
    result = subprocess.run([python, *args], cwd=root, capture_output=True, text=True)
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        if allow_conflict and ("CONFLICT" in output or "already" in output or "in place" in output):
            return {"status": "ALREADY_DONE", "detail": output.splitlines()[-1:][0] if output else ""}
        if allow_failure:
            return {"status": "NOT_READY", "detail": output.splitlines()[-1:][0] if output else ""}
        raise StepFailure(f"{args[0]} failed: {(output.splitlines() or ['no output'])[-1]}")
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {"status": "PASSED", "stdout": output}



def _at_research(work: Path, run_id: str, intent: str, steps: list[dict], research_root: Path, slug: str) -> dict:
    """The run pauses for the agent, never for a person, and says exactly what is left."""
    report = {
        "run_id": run_id,
        "intent": intent,
        "status": "RESEARCH_PENDING",
        "steps": steps,
        "next_action": {
            "actor": "agent",
            "project": str(research_root / "projects" / slug),
            "do": [
                "01_planning/research-plan.yaml のタスクを tools/task_runtime.py で進める",
                "02_evidence に証拠を集める。一次情報に当たり、開いて確かめてから引用する",
                "03_knowledge に観察・主張・関係・矛盾を書く",
                "04_decisions に判断・棄却案・不確実性を書く。棄却が無い調査は選んでいない",
                "05_production に要件・受入試験・試作計画・創作指針を書く",
            ],
            "acceptance": "tools/complete.py が COMPLETE を返し、tools/validate.py --root . が通ること",
            "resume": "同じ run-id でこの入口をもう一度呼ぶと、受け渡しから制作プランまで進む",
        },
        "state": str(work),
    }
    (work / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _run_orchestration(intent: str, workspace_root: Path, state_root: Path, run_id: str, purpose: str,
        slug: str, title: str, requested_at: str, python: str,
        research_root: Path | None = None, production_root: Path | None = None,
        limit: int = 1) -> dict:
    """Execute every step the repositories can do alone, in order, and record each one."""
    if (research_root is None) != (production_root is None):
        # Carrying on with one of the two would run a child tool in whatever directory
        # happens to be current, and report a step it did not take.
        raise StepFailure("--research-root and --production-root are given together or not at all")
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
        "--fixture", str(signals), "--project-id", slug, "--limit", str(limit),
        "--output", str(work / "selection.json"),
    ], python))

    record("propositions", _run_tool([
        "tools/proposition_provenance.py", "--selection", str(work / "selection.json"),
        "--candidates", str(work / "candidates.json"), "--gates", str(work / "gates.json"),
        "--fixture", str(signals), "--output", str(work / "propositions.json"),
    ], python))

    request_args = [
        "tools/build_research_request.py", "--propositions", str(work / "propositions.json"),
        "--signals", str(signals), "--title", title,
        "--requested-at", requested_at, "--output", str(work / "requests"),
    ]
    request_args += ["--all", "--slug", slug] if limit > 1 else ["--slug", slug]
    record("research-request", _run_tool(request_args, python))

    requests = sorted((work / "requests").glob("RR*.yaml"))
    request = requests[-1]

    if research_root is not None and limit > 1:
        # 100件を人が100回叩かないための入口。受理まで進めて、どのプロジェクトが
        # 調査待ちかを並べて返す。研究そのものはここから先の作業で、道具の実行ではない。
        accepted = []
        for path in requests:
            outcome = _run_child(
                research_root,
                ["tools/accept_research_request.py", str(path), "--apply", "--root", ".",
                 "--accepted-at", requested_at],
                python, allow_conflict=True)
            accepted.append({"request": path.name, "status": outcome.get("status"),
                             "project_id": outcome.get("project_id")})
        record("accept-batch", {"status": "PASSED", "accepted_count": len(accepted)})
        report = {
            "run_id": run_id, "intent": intent, "status": "BATCH_AT_RESEARCH",
            "steps": steps, "accepted": accepted, "state": str(work),
            "next_action": {
                "actor": "agent",
                "do": ["各プロジェクトで tools/next_action.py を回して調査を進める"],
                "acceptance": "各プロジェクトで tools/complete.py が COMPLETE を返すこと",
            },
        }
        (work / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report

    if research_root is not None:
        record("accept", _run_child(
            research_root, ["tools/accept_research_request.py", str(request), "--apply", "--root", ".",
                            "--accepted-at", requested_at], python, allow_conflict=True))

        complete = _run_child(research_root, ["tools/complete.py", f"project/{slug}"], python, allow_failure=True)
        record("research-complete", complete)
        if str(complete.get("status")) not in {"COMPLETE", "COMPLETE_WITH_GAPS"}:
            # 調査が済んでいない。人を待つのではなく、次に何をするかを返して同じ入口へ戻す。
            return _at_research(work, run_id, intent, steps, research_root, slug)

        record("handoff", _run_child(
            research_root, ["tools/build_handoff.py", f"projects/{slug}", "--root", ".",
                            "--generated-at", requested_at, "--research-commit", _head(research_root),
                            "--handoff-id", "HO001", "--revision", "1"], python, allow_conflict=True))
        record("export", _run_child(
            research_root, ["tools/export_handoff.py", f"projects/{slug}", "--root", ".",
                            "--output", str(work / "bundle")], python))
        record("accept-production", _run_child(
            production_root, ["tools/new_production.py", slug, "--handoff", str(work / "bundle"),
                              "--output-root", str(work / "production")], python))
        plan = _run_child(production_root, ["tools/build_plan.py", "--project-root",
                                            str(work / "production" / "production" / slug)], python)
        record("plan", plan)
        report = {
            "run_id": run_id, "intent": intent, "status": "PLAN_READY", "steps": steps,
            "plan": str(work / "production" / "production" / slug / "03_plan/production-plan.md"),
            "state": str(work),
        }
        (work / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report

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


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _run_input_pipeline(
    bundle: dict[str, Any],
    *,
    project_id: str,
    seed_input: str,
    selection_limit: int = 1,
    intent: str | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the synchronous signal pipeline while exposing only an intent digest."""
    from tools.candidate_gates import build_gate_report
    from tools.candidate_selection import INTENT_ALGORITHM, build_selection, intent_sha256, normalize_intent
    from tools.candidate_space import build_candidate_space
    from tools.consumer import import_signals
    from tools.proposition_provenance import build_provenance
    from tools.signal_bundle import validate_signal_bundle
    from tools.validate import load_yaml

    errors = validate_signal_bundle(bundle)
    if errors:
        raise ValueError("\n".join(errors))
    signals = bundle["records"]
    imported = import_signals(signals)
    registry = rules if rules is not None else load_yaml(DEFAULT_RULES_PATH)
    candidate_space = build_candidate_space(signals, registry, "run.candidates")
    gate_report = build_gate_report(candidate_space, signals, registry, "run.gates")
    selection = build_selection(
        candidate_space,
        gate_report,
        project_id,
        seed_input,
        selection_limit,
        "run.selection",
        signals=signals if intent is not None else None,
        intent=intent,
    )
    provenance = build_provenance(selection, candidate_space, gate_report, signals, registry, "run.provenance")
    research_source = next(
        (item for item in bundle.get("source_repositories", [])
         if item.get("repository") == "agentic-art-research"),
        bundle.get("source_repositories", [{}])[0],
    )
    result: dict[str, Any] = {
        "bundle": bundle,
        "consumer_package": imported,
        "candidate_space": candidate_space,
        "gate_report": gate_report,
        "selection": selection,
        "provenance": provenance,
        "execution_status": "RESEARCH_PENDING",
        "next_action": {
            "contract_version": "agent-action/v1",
            "run_id": project_id,
            "stage": "research",
            "child_repository": "agentic-art-research",
            "source_commit": research_source["commit"],
            "project_path": "project",
            "allowed_paths": ["project"],
            "forbidden_operations": HUMAN_OPERATIONS,
            "completion_command": "return agent-result/v1 with all declared checks",
            "resume_command": "resume the same run_id from supervisor.json",
            "requested_operations": [],
            "attempt": 1,
        },
    }
    if intent is not None:
        normalized = normalize_intent(intent, "run.intent")
        result["intent_sha256"] = intent_sha256(normalized)
        result["intent_algorithm"] = INTENT_ALGORITHM
    return result


def run(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Support both the v1 input pipeline and the full agent orchestration entrypoint."""
    if args and isinstance(args[0], dict):
        return _run_input_pipeline(*args, **kwargs)
    return _run_orchestration(*args, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--seed-input")
    parser.add_argument("--selection-limit", type=int, default=1)
    parser.add_argument("--intent", help="入力段の対話で人間から受け取ったもの")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--slug")
    parser.add_argument("--title")
    parser.add_argument("--requested-at")
    parser.add_argument("--purpose", default="artistic-research")
    parser.add_argument("--workspace-root", type=Path, default=ROOT / "repos")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--research-root", type=Path, help="指定すると調査の受理から制作プランまで進む")
    parser.add_argument("--production-root", type=Path)
    parser.add_argument("--limit", type=int, default=1,
                        help="選定する命題の件数。2以上でバッチになる")
    parser.add_argument("--child-python", default=sys.executable)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.bundle is not None:
            if not args.project_id or not args.seed_input:
                parser.error("--bundle requires --project-id and --seed-input")
            from tools.validate import load_yaml

            result = _run_input_pipeline(
                _load_json(args.bundle),
                project_id=args.project_id,
                seed_input=args.seed_input,
                selection_limit=args.selection_limit,
                intent=args.intent,
                rules=load_yaml(args.rules),
            )
            rendered = (canonical_json(result) + "\n").encode("utf-8")
            output = args.output or DEFAULT_OUTPUT_PATH
            if args.check:
                if output.read_bytes() != rendered:
                    raise ValueError(f"{output}: generated run bytes differ")
                changed = False
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                changed = output.exists() and output.read_bytes() == rendered
                if not changed:
                    output.write_bytes(rendered)
            summary: dict[str, Any] = {
                "changed": False if args.check else not changed,
                "command": "run",
                "selected_count": result["selection"]["selected_count"],
                "status": "PASSED",
            }
            if "intent_sha256" in result:
                summary["intent_algorithm"] = result["intent_algorithm"]
                summary["intent_sha256"] = result["intent_sha256"]
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return 0

        required = (args.run_id, args.slug, args.title, args.requested_at)
        if not all(required):
            parser.error("orchestration mode requires --run-id, --slug, --title, and --requested-at")
        report = _run_orchestration(args.intent or "", args.workspace_root, args.state_root, args.run_id,
                                    args.purpose, args.slug, args.title, args.requested_at, args.child_python,
                                    args.research_root, args.production_root, args.limit)
    except (StepFailure, OSError, IndexError, TypeError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "FAILED", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
