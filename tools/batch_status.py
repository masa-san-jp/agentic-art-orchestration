#!/usr/bin/env python3
"""Say where a hundred studies are, without asking any of them to move.

    python3 tools/batch_status.py --workspace-root <実クローン>
    python3 tools/batch_status.py --workspace-root <実クローン> --format json
    python3 tools/batch_status.py --report <state-root>/<run-id>/batch-report.jsonl

A batch that cannot be looked at has to be asked about, and asking is the
thing a hundred projects makes impossible. This reads and counts. It claims
nothing, writes nothing into a child, and changes no state: a status tool
that could move a task would eventually be blamed for moving one.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

if __package__ in {None, ""}:  # pragma: no cover - direct CLI use
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.validate import ROOT, load_json, load_yaml

MANIFEST_PATH = ROOT / "config/repositories.yaml"
STAGES = ("NOT_STARTED", "IN_PROGRESS", "TERMINAL", "HANDOFF", "PLANNED")
TERMINAL_STATUSES = {"COMPLETE", "COMPLETE_WITH_GAPS"}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def repository_drift(workspace_root: Path) -> list[dict]:
    """How far each checkout sits from its remote.

    A production checkout four commits behind its own main once produced a
    plan from code that had already been replaced, and nobody saw it because
    nothing showed it.
    """
    manifest = load_yaml(MANIFEST_PATH)
    rows = []
    for repository in manifest["repositories"]:
        path = workspace_root / repository["path"]
        if not path.is_dir():
            rows.append({"repository": repository["id"], "state": "MISSING", "behind": None, "ahead": None})
            continue
        behind = _git(path, "rev-list", "--count", "HEAD..origin/main")
        ahead = _git(path, "rev-list", "--count", "origin/main..HEAD")
        dirty = bool(_git(path, "status", "--porcelain"))
        rows.append({
            "repository": repository["id"],
            "state": "DIRTY" if dirty else ("MATCHED" if behind in ("", "0") and ahead in ("", "0") else "DIVERGED"),
            "behind": int(behind) if behind.isdigit() else None,
            "ahead": int(ahead) if ahead.isdigit() else None,
        })
    return rows


def _stage(state: dict, handoff: dict | None, plan: dict | None) -> tuple[str, int, int]:
    tasks = ((state.get("task_runtime") or {}).get("tasks") or {}) if isinstance(state, dict) else {}
    total = len(tasks)
    done = sum(1 for task in tasks.values() if task.get("status") == "SUCCEEDED")
    if plan is not None:
        return "PLANNED", done, total
    if handoff is not None and handoff.get("status") == "READY":
        return "HANDOFF", done, total
    if isinstance(state, dict) and state.get("status") in TERMINAL_STATUSES:
        return "TERMINAL", done, total
    if done == 0:
        return "NOT_STARTED", done, total
    return "IN_PROGRESS", done, total


def _maybe(path: Path, loader) -> dict | None:
    if not path.is_file():
        return None
    try:
        return loader(path)
    except (OSError, ValueError):
        return None


def survey(workspace_root: Path, production_output_root: Path | None = None) -> dict:
    research = workspace_root / "agentic-art-research" / "projects"
    projects = []
    for project in sorted(research.glob("*/")) if research.is_dir() else []:
        slug = project.name
        state = _maybe(project / "07_runtime/research-state.json", load_json) or {}
        handoff = _maybe(project / "05_production/production-handoff.yaml", load_yaml)
        plan = None
        if production_output_root is not None:
            plan = _maybe(production_output_root / "production" / slug / "03_plan/production-plan.yaml", load_yaml)
        stage, done, total = _stage(state, handoff, plan)
        projects.append({
            "slug": slug,
            "stage": stage,
            "tasks_done": done,
            "tasks_total": total,
            "project_status": state.get("status") if isinstance(state, dict) else None,
            "handoff_status": (handoff or {}).get("status"),
            "plan_startable": ((plan or {}).get("readiness") or {}).get("startable"),
        })
    return {
        "contract_version": "batch-status/v1",
        "workspace_root": str(workspace_root),
        "repositories": repository_drift(workspace_root),
        "projects": projects,
        "stage_counts": {stage: sum(1 for item in projects if item["stage"] == stage) for stage in STAGES},
    }


def summarise_report(path: Path) -> dict:
    """Roll up the batch's own log. Unmeasured is not zero, and is not reported as zero."""
    events = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    durations = [event["duration_seconds"] for event in events if isinstance(event.get("duration_seconds"), (int, float))]
    tokens = [event["tokens"] for event in events if isinstance(event.get("tokens"), int)]
    return {
        "contract_version": "batch-report-summary/v1",
        "event_count": len(events),
        "by_event_type": dict(Counter(str(event.get("event_type")) for event in events)),
        "projects_seen": len({str(event.get("project_id")) for event in events if event.get("project_id")}),
        "launches": sum(1 for event in events if event.get("event_type") == "AGENT_LAUNCHED"),
        "retries": sum(1 for event in events if event.get("event_type") == "TASK_RETRIED"),
        "failures": sum(1 for event in events if event.get("event_type") == "TASK_FAILED"),
        "duration_seconds_total": round(sum(durations), 3) if durations else None,
        "tokens_total": sum(tokens) if tokens else None,
        "tokens_measured_events": len(tokens),
        "unmeasured_note": None if tokens else "トークンは申告制で、この run では申告が無い（0 ではなく未計測）",
    }


def _table(survey_result: dict) -> str:
    lines = [f"{'repository':<24}{'state':<11}behind ahead"]
    for row in survey_result["repositories"]:
        lines.append(f"{row['repository']:<24}{row['state']:<11}{str(row['behind'] or 0):>6} {str(row['ahead'] or 0):>5}")
    lines.append("")
    counts = survey_result["stage_counts"]
    lines.append("  ".join(f"{stage} {counts[stage]}" for stage in STAGES))
    lines.append("")
    lines.append("project                              stage        tasks")
    for project in survey_result["projects"]:
        lines.append(f"{project['slug']:<37}{project['stage']:<13}{project['tasks_done']}/{project['tasks_total']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report where every project in a batch stands, read-only.")
    parser.add_argument("--workspace-root", type=Path, default=ROOT / "repos")
    parser.add_argument("--production-output-root", type=Path)
    parser.add_argument("--report", type=Path, help="batch-report.jsonl を集計する")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    try:
        result = survey(args.workspace_root.resolve(), args.production_output_root)
        if args.report is not None:
            result["report"] = summarise_report(args.report)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "FAILED", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_table(result))
        if "report" in result:
            print("")
            print(json.dumps(result["report"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
