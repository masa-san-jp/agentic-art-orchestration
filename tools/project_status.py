#!/usr/bin/env python3
"""Render deterministic project status from queue/state SSOT."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "execution/task-queue.yaml"
STATE_PATH = ROOT / "execution/state.yaml"
README_PATH = ROOT / "README.md"
SCHEMA_PATH = ROOT / "schemas/project-status.schema.json"
STATUSES = ("BACKLOG", "READY", "IN_PROGRESS", "BLOCKED", "DONE")
MARKER_START = "<!-- project-status:start -->"
MARKER_END = "<!-- project-status:end -->"

try:
    from tools.validate import _schema_errors, load_json, load_yaml
except ModuleNotFoundError:  # pragma: no cover - exercised by direct CLI use
    sys.path.insert(0, str(ROOT))
    from tools.validate import _schema_errors, load_json, load_yaml


class ProjectStatusError(ValueError):
    """An input or generated project-status contract is invalid."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _integrity_errors(queue: object, state: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(queue, dict):
        return ["queue must be an object"]
    if not isinstance(state, dict):
        return ["state must be an object"]
    tasks = queue.get("tasks")
    if not isinstance(tasks, list):
        return ["queue.tasks must be a list"]

    ids = [task.get("id") if isinstance(task, dict) else None for task in tasks]
    seen: set[object] = set()
    duplicate_ids: list[object] = []
    for task_id in ids:
        marker = task_id if isinstance(task_id, (str, int, float, bool, type(None))) else repr(task_id)
        if marker in seen and marker not in duplicate_ids:
            duplicate_ids.append(marker)
        seen.add(marker)
    if duplicate_ids:
        errors.append(f"duplicate task IDs: {duplicate_ids!r}")

    by_id = {
        task.get("id"): task
        for task in tasks
        if isinstance(task, dict) and isinstance(task.get("id"), str)
    }

    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"tasks[{index}] must be an object")
            continue
        task_id = task.get("id", f"<index-{index}>")
        dependencies = task.get("depends_on", [])
        if not isinstance(dependencies, list):
            errors.append(f"{task_id}.depends_on must be a list")
            continue
        for dependency in dependencies:
            if dependency not in by_id:
                errors.append(f"{task_id} references unknown task {dependency!r}")
        if task.get("status") == "READY":
            incomplete = [
                dependency
                for dependency in dependencies
                if by_id.get(dependency, {}).get("status") != "DONE"
            ]
            if incomplete:
                errors.append(f"{task_id} is READY with incomplete dependencies {incomplete!r}")

    state_refs = {
        "active_task": state.get("active_task"),
        "checkpoint.task": (state.get("checkpoint") or {}).get("task") if isinstance(state.get("checkpoint"), dict) else None,
        "resume_from.task": (state.get("resume_from") or {}).get("task") if isinstance(state.get("resume_from"), dict) else None,
        "last_completed_task": state.get("last_completed_task"),
    }
    for field, task_id in state_refs.items():
        if task_id is not None and task_id not in by_id:
            errors.append(f"state.{field} references unknown task {task_id!r}")

    active_task = state.get("active_task")
    if active_task in by_id and by_id[active_task].get("status") == "DONE":
        errors.append(f"state.active_task references DONE task {active_task!r}")

    for task in tasks:
        if isinstance(task, dict) and task.get("status") == "BLOCKED":
            reason = task.get("blocker")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{task.get('id')!r} is BLOCKED without a recorded blocker reason")
    return errors


def _counts(tasks: list[dict]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for task in tasks:
        status = task.get("status")
        if status in counts:
            counts[status] += 1
    counts["total"] = len(tasks)
    return counts


def _external_ready(task: dict) -> bool:
    from tools.issue_intake import aak_dependency_evidence_ready
    return aak_dependency_evidence_ready(task)


def _ready(tasks: list[dict]) -> list[str]:
    by_id = {task.get("id"): task for task in tasks}
    return sorted(
        task.get("id")
        for task in tasks
        if task.get("status") == "READY"
        and _external_ready(task)
        and all(by_id.get(dependency, {}).get("status") == "DONE" for dependency in task.get("depends_on", []))
    )


def _blocked(tasks: list[dict]) -> list[dict]:
    return [
        {"task_id": task.get("id"), "reason": task.get("blocker")}
        for task in sorted(tasks, key=lambda item: str(item.get("id")))
        if task.get("status") == "BLOCKED"
    ]


def _next_task(tasks: list[dict]) -> str | None:
    ready = _ready(tasks)
    if ready:
        return ready[0]
    by_id = {task.get("id"): task for task in tasks}
    eligible_backlog = sorted(
        task.get("id")
        for task in tasks
        if task.get("status") == "BACKLOG"
        and _external_ready(task)
        and all(by_id.get(dependency, {}).get("status") == "DONE" for dependency in task.get("depends_on", []))
    )
    return eligible_backlog[0] if eligible_backlog else None


def _current(state: Mapping[str, object]) -> dict:
    resume_from = state.get("resume_from")
    next_action = resume_from.get("action") if isinstance(resume_from, dict) else state.get("next_action")
    return {
        "task_id": state.get("active_task"),
        "repository": state.get("active_repository"),
        "checkpoint": state.get("checkpoint"),
        "next_action": next_action,
    }


def validate_project_status(report: object, queue: object, state: object) -> list[str]:
    """Return schema and derived-field errors for a generated status report."""
    errors: list[str] = []
    schema = load_json(SCHEMA_PATH)
    errors.extend(_schema_errors(report, schema))
    errors.extend(_integrity_errors(queue, state))
    if not isinstance(report, dict) or not isinstance(queue, dict) or not isinstance(queue.get("tasks"), list):
        return errors
    expected_counts = _counts(queue["tasks"])
    if report.get("counts") != expected_counts:
        errors.append(f"counts mismatch: expected {expected_counts!r}, got {report.get('counts')!r}")
    declared_counts = queue.get("counts")
    if declared_counts is not None and declared_counts != expected_counts:
        errors.append(f"queue counts mismatch: expected {expected_counts!r}, got {declared_counts!r}")
    if report.get("ready") != _ready(queue["tasks"]):
        errors.append("ready list does not match queue dependency resolution")
    if report.get("blocked") != _blocked(queue["tasks"]):
        errors.append("blocked list does not match queue blocker reasons")
    expected_next = _next_task(queue["tasks"])
    if report.get("next_task") != expected_next:
        errors.append("next_task is not the lowest-ID eligible READY task")
    return errors


def build_project_status(queue: dict, state: dict, source_hashes: Mapping[str, str]) -> dict:
    """Build and validate a byte-stable project-status envelope."""
    integrity_errors = _integrity_errors(queue, state)
    if integrity_errors:
        raise ProjectStatusError("; ".join(integrity_errors))
    tasks = queue["tasks"]
    report = {
        "contract_version": "project-status/v1",
        "source_hashes": {"queue": source_hashes.get("queue"), "state": source_hashes.get("state")},
        "counts": _counts(tasks),
        "current": _current(state),
        "ready": _ready(tasks),
        "blocked": _blocked(tasks),
        "next_task": _next_task(tasks),
        "source_updated_at": state.get("updated_at"),
    }
    errors = validate_project_status(report, queue, state)
    if errors:
        raise ProjectStatusError("; ".join(errors))
    return report


build_status = build_project_status


def load_project_status(queue_path: Path = QUEUE_PATH, state_path: Path = STATE_PATH) -> dict:
    queue = load_yaml(queue_path)
    state = load_yaml(state_path)
    return build_project_status(
        queue,
        state,
        {"queue": sha256_file(queue_path), "state": sha256_file(state_path)},
    )


def render_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_markdown(report: dict) -> str:
    counts = report["counts"]
    current = report["current"]
    checkpoint = current.get("checkpoint") if isinstance(current.get("checkpoint"), dict) else {}
    checkpoint_label = checkpoint.get("task") or checkpoint.get("start_point") or "null"
    lines = [
        "## Project status",
        "",
        "Source of truth: `execution/task-queue.yaml` and `execution/state.yaml`.",
        f"Source updated at: `{report['source_updated_at'] or 'null'}`.",
        "",
        "| BACKLOG | READY | IN_PROGRESS | BLOCKED | DONE | Total |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {counts['BACKLOG']} | {counts['READY']} | {counts['IN_PROGRESS']} | {counts['BLOCKED']} | {counts['DONE']} | {counts['total']} |",
        "",
        f"Current task: `{current['task_id'] or 'null'}`; repository: `{current['repository'] or 'null'}`; checkpoint: `{checkpoint_label}`.",
        f"Next action: {current['next_action'] or '`null`'}",
        f"Ready: {', '.join(f'`{task_id}`' for task_id in report['ready']) or 'none'}.",
        f"Next task: `{report['next_task'] or 'null'}`.",
        "Blocked:",
    ]
    if report["blocked"]:
        lines.extend(f"- `{item['task_id']}`: {item['reason']}" for item in report["blocked"])
    else:
        lines.append("- none")
    lines.extend([
        "",
        "Generated by `python3 tools/project_status.py --update-readme`.",
    ])
    return "\n".join(lines) + "\n"


def render_readme_block(report: dict) -> str:
    return f"{MARKER_START}\n{render_markdown(report)}{MARKER_END}\n"


def replace_readme_marker(text: str, report: dict) -> str:
    if text.count(MARKER_START) != 1 or text.count(MARKER_END) != 1:
        raise ProjectStatusError("README must contain exactly one project-status marker pair")
    start = text.index(MARKER_START)
    end = text.index(MARKER_END, start) + len(MARKER_END)
    if text.index(MARKER_END) < start:
        raise ProjectStatusError("README project-status markers are out of order")
    return text[:start] + render_readme_block(report).rstrip("\n") + text[end:]


def update_readme(readme_path: Path = README_PATH, queue_path: Path = QUEUE_PATH, state_path: Path = STATE_PATH) -> bool:
    report = load_project_status(queue_path, state_path)
    current = readme_path.read_text(encoding="utf-8")
    updated = replace_readme_marker(current, report)
    changed = updated != current
    if changed:
        readme_path.write_text(updated, encoding="utf-8")
    return changed


def check_readme(readme_path: Path = README_PATH, queue_path: Path = QUEUE_PATH, state_path: Path = STATE_PATH) -> bool:
    report = load_project_status(queue_path, state_path)
    current = readme_path.read_text(encoding="utf-8")
    return replace_readme_marker(current, report) == current


def main() -> int:
    parser = argparse.ArgumentParser(description="Render deterministic project status from queue/state")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--format", choices=("json", "markdown"))
    output.add_argument("--update-readme", action="store_true")
    output.add_argument("--check-readme", action="store_true")
    args = parser.parse_args()
    try:
        if args.format:
            report = load_project_status()
            sys.stdout.write(render_json(report) if args.format == "json" else render_markdown(report))
            return 0
        if args.update_readme:
            changed = update_readme()
            print(json.dumps({"command": "project-status", "changed": changed}, sort_keys=True))
            return 0
        if args.check_readme:
            if not check_readme():
                print("ERROR: README project status is stale; remediation: run --update-readme", file=sys.stderr)
                return 1
            print("OK: README project status matches queue/state")
            return 0
        parser.error("choose --format, --update-readme, or --check-readme")
    except (OSError, ProjectStatusError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
