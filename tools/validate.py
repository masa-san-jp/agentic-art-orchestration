#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SHA40 = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_FILES = [
    "README.md",
    "AGENTS.md",
    "PLANS.md",
    "config/repositories.yaml",
    "config/orchestration.yaml",
    "execution/task-queue.yaml",
    "execution/state.yaml",
    "execution/handoff.md",
    "docs/20260811-agentic-art-orchestration-system-design-specification.md",
    "docs/20260811-agentic-art-orchestration-repository-execution-plan.md",
]
STATUSES = {"BACKLOG", "READY", "IN_PROGRESS", "BLOCKED", "DONE"}
ROLES = {"input-kb", "consumer-runtime", "control-plane-extension"}


def load_yaml(path: Path):
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except Exception as exc:
        raise ValueError(f"{path.relative_to(ROOT)}: YAML parse failed: {exc}") from exc


def validate_repositories(errors: list[str]) -> None:
    data = load_yaml(ROOT / "config/repositories.yaml")
    repos = data.get("repositories", []) if isinstance(data, dict) else []
    if len(repos) != 4:
        errors.append("config/repositories.yaml: expected exactly four v1 repositories")
        return
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    seen_names: set[str] = set()
    required = ("id", "full_name", "url", "path", "role", "authority",
                "default_branch", "observed_commit", "quality_gates")
    for index, repo in enumerate(repos):
        prefix = f"config/repositories.yaml: repositories[{index}]"
        for field in required:
            if field not in repo or repo[field] in (None, "", []):
                errors.append(f"{prefix}.{field}: required; add a non-empty value")
        for value, seen, label in (
            (repo.get("id"), seen_ids, "id"),
            (repo.get("path"), seen_paths, "path"),
            (repo.get("full_name"), seen_names, "full_name"),
        ):
            if value in seen:
                errors.append(f"{prefix}.{label}: duplicate {value!r}")
            seen.add(value)
        if repo.get("role") not in ROLES:
            errors.append(f"{prefix}.role: unknown role {repo.get('role')!r}")
        if not SHA40.fullmatch(str(repo.get("observed_commit", ""))):
            errors.append(f"{prefix}.observed_commit: expected lowercase 40-character SHA")
        if not str(repo.get("url", "")).startswith("https://github.com/"):
            errors.append(f"{prefix}.url: expected HTTPS github.com clone URL")


def validate_tasks(errors: list[str]) -> None:
    data = load_yaml(ROOT / "execution/task-queue.yaml")
    tasks = data.get("tasks", []) if isinstance(data, dict) else []
    ids = [task.get("id") for task in tasks]
    if len(ids) != len(set(ids)):
        errors.append("execution/task-queue.yaml: task IDs must be unique")
    by_id = {task.get("id"): task for task in tasks}
    for task in tasks:
        task_id = task.get("id", "<missing>")
        for field in ("milestone", "title", "status", "depends_on", "acceptance", "checks"):
            if field not in task:
                errors.append(f"execution/task-queue.yaml: {task_id}.{field} is required")
        if task.get("status") not in STATUSES:
            errors.append(f"execution/task-queue.yaml: {task_id}.status is unknown")
        deps = task.get("depends_on", [])
        for dep in deps:
            if dep not in by_id:
                errors.append(f"execution/task-queue.yaml: {task_id} depends on missing {dep}")
        if task.get("status") == "READY":
            incomplete = [dep for dep in deps if by_id.get(dep, {}).get("status") != "DONE"]
            if incomplete:
                errors.append(f"execution/task-queue.yaml: {task_id} READY with incomplete {incomplete}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str, chain: list[str]) -> None:
        if task_id in visiting:
            errors.append(f"execution/task-queue.yaml: cycle {' -> '.join(chain + [task_id])}")
            return
        if task_id in visited or task_id not in by_id:
            return
        visiting.add(task_id)
        for dep in by_id[task_id].get("depends_on", []):
            visit(dep, chain + [task_id])
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id, [])


def validate() -> list[str]:
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            errors.append(f"{rel}: required file is missing")
    if errors:
        return errors
    try:
        validate_repositories(errors)
        validate_tasks(errors)
        state = load_yaml(ROOT / "execution/state.yaml")
        if state.get("last_completed_task") is None:
            errors.append("execution/state.yaml: last_completed_task is required")
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate orchestration bootstrap")
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.parse_args()
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK: orchestration bootstrap is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
