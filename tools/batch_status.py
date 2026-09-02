#!/usr/bin/env python3
"""Read-only cross-project status and append-only batch report aggregation."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

try:
    from tools.validate import _schema_errors, load_json, load_yaml
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.validate import _schema_errors, load_json, load_yaml


ROOT = Path(__file__).resolve().parents[1]
REPORT_EVENT_SCHEMA_PATH = ROOT / "schemas/batch-report-event.schema.json"
STATUS_CONTRACT_VERSION = "batch-status/v1"
REPORT_CONTRACT_VERSION = "batch-report/v1"
EVENT_CONTRACT_VERSION = "batch-report-event/v1"
STAGES = ("NOT_STARTED", "IN_PROGRESS", "TERMINAL", "HANDOFF", "PLANNED")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
COMPLETED_STATUSES = {"SUCCEEDED", "DONE", "COMPLETE", "COMPLETED", "PASSED", "SUCCESS"}
TERMINAL_STATUSES = COMPLETED_STATUSES | {
    "COMPLETE_WITH_GAPS",
    "PLAN_READY",
    "TERMINAL",
}
HANDOFF_STATUSES = {"ACCEPTED", "HANDOFF_ACCEPTED", "READY", "COMPLETE", "COMPLETED", "EXPORTED"}


class BatchStatusError(ValueError):
    """A malformed or unsafe batch status input."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _resolved_inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _relative(root: Path, path: Path) -> str:
    if not _resolved_inside(root, path):
        raise BatchStatusError(f"input escapes workspace root: {path}")
    return path.resolve().relative_to(root.resolve()).as_posix()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BatchStatusError(f"cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BatchStatusError(f"JSON input must be an object: {path}")
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = load_yaml(path)
    except ValueError as exc:
        raise BatchStatusError(str(exc)) from exc
    if not isinstance(value, dict):
        raise BatchStatusError(f"YAML input must be an object: {path}")
    return value


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _task_items(state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    tasks = state.get("tasks")
    if isinstance(tasks, list):
        return [item for item in tasks if isinstance(item, Mapping)]
    if isinstance(tasks, Mapping):
        return [item for item in tasks.values() if isinstance(item, Mapping)]
    return []


def _task_progress(state: Mapping[str, Any]) -> tuple[int, int, list[str]]:
    tasks = _task_items(state)
    unknowns: list[str] = []
    if tasks:
        total = len(tasks)
        completed = sum(
            1
            for task in tasks
            if _string(task.get("status")) and task["status"].upper() in COMPLETED_STATUSES
        )
        if any(not _string(task.get("status")) for task in tasks):
            unknowns.append("one or more research tasks have no status")
        return completed, total, unknowns

    total_value = state.get("task_total")
    completed_value = state.get("task_completed")
    if isinstance(total_value, int) and not isinstance(total_value, bool) and total_value >= 0:
        completed = completed_value if isinstance(completed_value, int) and completed_value >= 0 else 0
        if completed > total_value:
            unknowns.append("task_completed exceeds task_total")
            completed = total_value
        return completed, total_value, unknowns
    if total_value is not None or completed_value is not None:
        unknowns.append("task progress counters are invalid")
    return 0, 0, unknowns


def _status_value(data: Mapping[str, Any]) -> str | None:
    for key in ("status", "state", "handoff_status", "acceptance_status"):
        value = _string(data.get(key))
        if value:
            return value.upper()
    return None


def _plan_startable(plan: Mapping[str, Any]) -> bool:
    readiness = plan.get("readiness")
    return isinstance(readiness, Mapping) and readiness.get("startable") is True


def _project_status(
    root: Path,
    state_path: Path,
    state: Mapping[str, Any],
) -> dict[str, Any]:
    project_root = state_path.parent.parent
    project_id = _string(state.get("project_id")) or _string(state.get("project_slug")) or project_root.name
    if ID_PATTERN.fullmatch(project_id) is None:
        raise BatchStatusError(f"project ID is unsafe in {_relative(root, state_path)}: {project_id!r}")

    completed, total, unknowns = _task_progress(state)
    research_status = _status_value(state)
    handoff_path = project_root / "05_production" / "production-handoff.yaml"
    plan_path = project_root / "03_plan" / "production-plan.yaml"
    handoff_status: str | None = None
    plan_startable: bool | None = None
    source_files = [{"kind": "research_state", "path": _relative(root, state_path), "sha256": sha256_file(state_path)}]

    if handoff_path.exists():
        if not _resolved_inside(root, handoff_path):
            raise BatchStatusError(f"handoff input escapes workspace root: {handoff_path}")
        handoff = _read_yaml(handoff_path)
        handoff_status = _status_value(handoff)
        source_files.append({"kind": "production_handoff", "path": _relative(root, handoff_path), "sha256": sha256_file(handoff_path)})
        if handoff_status not in HANDOFF_STATUSES:
            unknowns.append("production handoff status is absent or unrecognized")
    if plan_path.exists():
        if not _resolved_inside(root, plan_path):
            raise BatchStatusError(f"plan input escapes workspace root: {plan_path}")
        plan = _read_yaml(plan_path)
        plan_startable = _plan_startable(plan)
        source_files.append({"kind": "production_plan", "path": _relative(root, plan_path), "sha256": sha256_file(plan_path)})
        if not plan_startable:
            unknowns.append("production plan is present but not startable")

    if plan_startable is True:
        stage = "PLANNED"
    elif handoff_status in HANDOFF_STATUSES:
        stage = "HANDOFF"
    elif research_status in TERMINAL_STATUSES or (total > 0 and completed == total and not unknowns):
        stage = "TERMINAL"
    elif completed > 0:
        stage = "IN_PROGRESS"
    else:
        stage = "NOT_STARTED"

    return {
        "project_id": project_id,
        "stage": stage,
        "task_completed": completed,
        "task_total": total,
        "research_status": research_status,
        "handoff_status": handoff_status,
        "plan_startable": plan_startable,
        "state_quality": "UNKNOWN" if unknowns else "OBSERVED",
        "unknowns": sorted(set(unknowns)),
        "source_files": sorted(source_files, key=lambda item: (item["kind"], item["path"])),
    }


def _run_git(repo: Path, args: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _git_repository(root: Path, repo: Path) -> dict[str, Any]:
    unknowns: list[str] = []
    code, branch, _ = _run_git(repo, ["symbolic-ref", "--short", "-q", "HEAD"])
    if code:
        branch = None
        unknowns.append("detached or unavailable branch")
    _, head, _ = _run_git(repo, ["rev-parse", "HEAD"])
    if not SHA40_PATTERN.fullmatch(head):
        head = None
        unknowns.append("HEAD is unavailable")
    status_code, status, _ = _run_git(repo, ["status", "--porcelain", "--untracked-files=all"])
    dirty: bool | None = bool(status) if status_code == 0 else None
    if status_code:
        dirty = None
        unknowns.append("Git status is unavailable")

    def count(revision: str) -> int | None:
        code, value, _ = _run_git(repo, ["rev-list", "--count", revision])
        if code or not value.isdigit():
            unknowns.append(f"cannot compare {revision}")
            return None
        return int(value)

    origin_ahead = count("HEAD..origin/main")
    local_ahead = count("origin/main..HEAD")
    return {
        "repository_id": repo.name,
        "path": _relative(root, repo),
        "branch": branch,
        "head": head,
        "dirty": dirty,
        "origin_ahead": origin_ahead,
        "local_ahead": local_ahead,
        "state_quality": "UNKNOWN" if unknowns else "OBSERVED",
        "unknowns": sorted(set(unknowns)),
    }


def _discover_states(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("research-state.json"):
        if path.parent.name != "07_runtime" or not path.is_file():
            continue
        if _resolved_inside(root, path):
            paths.append(path)
    return sorted(paths, key=lambda path: _relative(root, path))


def scan_workspace(workspace_root: str | Path) -> dict[str, Any]:
    """Observe project and direct-child repository status without writing anything."""
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise BatchStatusError(f"workspace root is not a directory: {root}")

    projects = [_project_status(root, path, _read_json(path)) for path in _discover_states(root)]
    repositories = [
        _git_repository(root, path)
        for path in sorted(root.iterdir(), key=lambda item: item.name)
        if path.is_dir() and (path / ".git").exists() and _resolved_inside(root, path)
    ]
    return {
        "contract_version": STATUS_CONTRACT_VERSION,
        "workspace_root_hash": sha256_bytes(str(root).encode("utf-8")),
        "read_only": True,
        "repositories": repositories,
        "projects": projects,
        "stage_vocabulary": list(STAGES),
    }


def validate_batch_report_event(data: object, source: str = "batch-report-event") -> list[str]:
    """Validate one closed JSONL event and its event-specific measured field."""
    schema = load_json(REPORT_EVENT_SCHEMA_PATH)
    errors = list(_schema_errors(data, schema))
    if not isinstance(data, Mapping):
        return [f"{source}: {error}" for error in errors]
    event_type = data.get("event_type")
    if event_type == "DURATION" and data.get("duration_seconds") is None:
        errors.append("$: DURATION event requires duration_seconds; record a measured value")
    if event_type == "TOKENS" and data.get("token_count") is None:
        errors.append("$: TOKENS event requires token_count; record a measured value")
    return [f"{source}: {error}" for error in errors]


def _report_events(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise BatchStatusError(f"cannot read report {path}: {exc}") from exc
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BatchStatusError(f"{path}:{line_number}: invalid JSONL event: {exc}") from exc
        errors = validate_batch_report_event(event, f"{path}:{line_number}")
        if errors:
            raise BatchStatusError("\n".join(errors))
        event_id = event["event_id"]
        if event_id in seen:
            raise BatchStatusError(f"{path}:{line_number}: duplicate event_id {event_id!r}")
        seen.add(event_id)
        events.append(event)
    return events


def aggregate_report(report_path: str | Path) -> dict[str, Any]:
    events = _report_events(Path(report_path))
    counts = {"起動": 0, "完了": 0, "失敗": 0, "再試行": 0}
    event_aliases = {"STARTED": "起動", "COMPLETED": "完了", "FAILED": "失敗", "RETRY": "再試行"}
    durations = [event["duration_seconds"] for event in events if event.get("duration_seconds") is not None]
    tokens = [event["token_count"] for event in events if event.get("token_count") is not None]
    for event in events:
        label = event_aliases.get(event["event_type"])
        if label:
            counts[label] += 1
    duration_summary: dict[str, Any]
    if durations:
        duration_summary = {
            "total_seconds": sum(durations),
            "min_seconds": min(durations),
            "max_seconds": max(durations),
            "display": f"{sum(durations):g}s",
        }
    else:
        duration_summary = {"total_seconds": None, "min_seconds": None, "max_seconds": None, "display": "未計測"}
    token_summary: dict[str, Any] = {
        "total": sum(tokens) if tokens else None,
        "display": str(sum(tokens)) if tokens else "未計測",
    }
    return {
        "contract_version": REPORT_CONTRACT_VERSION,
        "event_count": len(events),
        "project_count": len({event["project_id"] for event in events}),
        "projects": sorted({event["project_id"] for event in events}),
        "counts": counts,
        "duration": duration_summary,
        "tokens": token_summary,
        "source_report": {"path": Path(report_path).name, "sha256": sha256_file(Path(report_path))},
    }


def render_status_table(report: Mapping[str, Any]) -> str:
    lines = ["Repositories:"]
    for item in report["repositories"]:
        remote = item["origin_ahead"] if item["origin_ahead"] is not None else "UNKNOWN"
        lines.append(f"- {item['repository_id']}: origin/main ahead of HEAD={remote}, state={item['state_quality']}")
    lines.append("Projects:")
    for item in report["projects"]:
        lines.append(f"- {item['project_id']}: {item['stage']} ({item['task_completed']}/{item['task_total']})")
    return "\n".join(lines)


def render_report_summary(summary: Mapping[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "Batch report:",
            f"起動: {counts['起動']}",
            f"完了: {counts['完了']}",
            f"失敗: {counts['失敗']}",
            f"再試行: {counts['再試行']}",
            f"所要: {summary['duration']['display']}",
            f"tokens: {summary['tokens']['display']}",
        ]
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only batch status and report aggregator")
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.add_argument("--report", type=Path, help="append-only batch-report.jsonl to aggregate")
    parser.add_argument("--format", choices=("table", "json"), default="table")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = aggregate_report(args.report) if args.report else scan_workspace(args.workspace_root)
    except (BatchStatusError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    elif args.report:
        print(render_report_summary(result))
    else:
        print(render_status_table(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
