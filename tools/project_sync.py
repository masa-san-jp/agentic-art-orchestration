#!/usr/bin/env python3
"""Plan idempotent GitHub Projects #4 synchronization with local fallback."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = re.compile(r"^[A-Z][A-Z0-9-]+-[0-9]{3}$")
ALLOWED_STATES = {"BACKLOG", "READY", "IN_PROGRESS", "DONE", "BLOCKED"}


class ProjectSyncError(ValueError):
    """A project mapping or synchronization plan is unsafe."""


def _error(detail: str, remediation: str) -> ProjectSyncError:
    return ProjectSyncError(f"project sync: {detail}; remediation: {remediation}")


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise _error(f"{field} must be a list of non-empty strings", f"repair {field} in the project mapping")
    return sorted(set(value))


def _validate_config(config: Mapping[str, object]) -> None:
    if config.get("version") != 1:
        raise _error("project mapping version must be 1", "use the supported mapping version")
    if config.get("project_number") != 4:
        raise _error("project_number must be 4", "configure the declared human-visible Project #4")
    status_map = config.get("status_map")
    if not isinstance(status_map, Mapping) or set(status_map) != ALLOWED_STATES:
        raise _error("status_map must cover every queue state exactly", "map BACKLOG, READY, IN_PROGRESS, DONE, and BLOCKED")
    if any(not isinstance(value, str) or not value for value in status_map.values()):
        raise _error("status_map values must be non-empty strings", "use human-visible Project status names")
    priorities = config.get("priority_by_milestone")
    if not isinstance(priorities, Mapping) or any(not isinstance(value, int) or value < 0 for value in priorities.values()):
        raise _error("priority_by_milestone must map milestones to non-negative integers", "declare deterministic priorities")
    _strings(config.get("default_target_repositories"), "default_target_repositories")
    if not isinstance(config.get("default_human_gate"), bool):
        raise _error("default_human_gate must be boolean", "declare whether unmapped tasks require review")


def local_projection(tasks: list[dict], state: Mapping[str, object], config: Mapping[str, object]) -> list[dict]:
    """Project local queue fields into stable, human-visible Project fields."""
    _validate_config(config)
    status_map = config["status_map"]
    priorities = config["priority_by_milestone"]
    default_targets = config["default_target_repositories"]
    result: list[dict] = []
    seen: set[str] = set()
    for task in sorted(tasks, key=lambda item: str(item.get("id"))):
        if not isinstance(task, dict):
            raise _error("queue task must be an object", "repair execution/task-queue.yaml")
        task_id = task.get("id")
        task_state = task.get("status")
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            raise _error(f"invalid task ID {task_id!r}", "use the queue task ID as the stable Project item key")
        if task_id in seen:
            raise _error(f"duplicate task ID {task_id!r}", "declare each Project item key once")
        seen.add(task_id)
        if task_state not in ALLOWED_STATES:
            raise _error(f"unknown queue state {task_state!r}", "use a state declared by project status_map")
        milestone = task.get("milestone")
        if milestone not in priorities:
            raise _error(f"milestone {milestone!r} has no priority", "add the milestone to priority_by_milestone")
        targets = task.get("target_repositories", default_targets)
        human_gate = task.get("human_gate", config["default_human_gate"])
        if not isinstance(human_gate, bool):
            raise _error(f"human_gate for {task_id} must be boolean", "declare a boolean human review flag")
        result.append(
            {
                "task_id": task_id,
                "title": task.get("title", task_id),
                "state": task_state,
                "status": status_map[task_state],
                "priority": task.get("priority", priorities[milestone]),
                "target_repositories": _strings(targets, f"target_repositories for {task_id}"),
                "human_gate": human_gate,
                "run_id": state.get("active_task") if state.get("active_task") == task_id else None,
            }
        )
    return result


def _remote_by_task(remote_items: list[dict]) -> dict[str, dict]:
    by_task: dict[str, dict] = {}
    for item in remote_items:
        if not isinstance(item, dict):
            raise _error("remote Project item must be an object", "return metadata-only Project item records")
        task_id = item.get("task_id")
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            raise _error(f"remote item has invalid task_id {task_id!r}", "use the stable local task ID")
        if task_id in by_task:
            raise _error(
                f"remote Project has duplicate item for {task_id!r}",
                "resolve duplicate human-visible items before syncing; do not delete automatically",
            )
        by_task[task_id] = item
    return by_task


def _field_diff(expected: dict, actual: dict) -> dict:
    fields = ("title", "status", "priority", "target_repositories", "human_gate", "run_id")
    return {
        field: expected[field]
        for field in fields
        if actual.get(field) != expected[field]
    }


def build_sync_plan(
    tasks: list[dict],
    state: Mapping[str, object],
    config: Mapping[str, object],
    remote_items: list[dict] | None = None,
    api_available: bool = False,
) -> dict:
    """Return a side-effect-free plan; API outage never blocks local queue execution."""
    projected = local_projection(tasks, state, config)
    plan = {
        "version": 1,
        "project_number": 4,
        "mode": "REMOTE" if api_available else "LOCAL_ONLY",
        "local_execution": "CONTINUE",
        "items": projected,
        "operations": [],
        "orphan_remote_items": [],
        "remote_error": None if api_available else "Project API unavailable; local queue remains authoritative for execution",
    }
    if not api_available:
        return plan
    remote = _remote_by_task(remote_items or [])
    local_ids = {item["task_id"] for item in projected}
    for item in projected:
        existing = remote.get(item["task_id"])
        if existing is None:
            plan["operations"].append({"action": "CREATE", "task_id": item["task_id"], "fields": item})
            continue
        differences = _field_diff(item, existing)
        if differences:
            plan["operations"].append(
                {"action": "UPDATE", "task_id": item["task_id"], "item_id": existing.get("item_id"), "fields": differences}
            )
        else:
            plan["operations"].append({"action": "UNCHANGED", "task_id": item["task_id"], "item_id": existing.get("item_id")})
    for task_id in sorted(set(remote) - local_ids):
        plan["orphan_remote_items"].append(
            {"task_id": task_id, "item_id": remote[task_id].get("item_id"), "action": "MANUAL_REVIEW"}
        )
    plan["operations"] = sorted(plan["operations"], key=lambda operation: operation["task_id"])
    return plan


def apply_plan_to_metadata(remote_items: list[dict], plan: dict) -> list[dict]:
    """Apply only metadata operations to a supplied fixture, never to GitHub."""
    result = copy.deepcopy(remote_items)
    by_task = {item["task_id"]: item for item in result}
    for operation in plan.get("operations", []):
        action = operation["action"]
        task_id = operation["task_id"]
        if action == "CREATE":
            created = copy.deepcopy(operation["fields"])
            created["item_id"] = f"fixture:{task_id}"
            result.append(created)
            by_task[task_id] = created
        elif action == "UPDATE":
            by_task[task_id].update(copy.deepcopy(operation["fields"]))
    return sorted(result, key=lambda item: item["task_id"])


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan idempotent GitHub Projects #4 synchronization")
    parser.add_argument("--queue", type=Path, default=ROOT / "execution/task-queue.yaml")
    parser.add_argument("--state", type=Path, default=ROOT / "execution/state.yaml")
    parser.add_argument("--config", type=Path, default=ROOT / "config/project.yaml")
    parser.add_argument("--remote-items", type=Path, default=None, help="metadata-only JSON fixture returned by a Project connector")
    parser.add_argument("--api-unavailable", action="store_true", help="exercise local-only fallback without network access")
    parser.add_argument("--output", type=Path, default=ROOT / "data/project-sync.json")
    args = parser.parse_args()
    try:
        with args.queue.open(encoding="utf-8") as handle:
            queue = yaml.safe_load(handle)
        with args.state.open(encoding="utf-8") as handle:
            state = yaml.safe_load(handle)
        with args.config.open(encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        remote_items = []
        if args.remote_items is not None:
            with args.remote_items.open(encoding="utf-8") as handle:
                remote_items = json.load(handle)
        tasks = queue.get("tasks", []) if isinstance(queue, dict) else []
        plan = build_sync_plan(tasks, state, config, remote_items, api_available=not args.api_unavailable and args.remote_items is not None)
        _write_atomic(args.output.resolve(), json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
