#!/usr/bin/env python3
"""Build a deterministic, task-minimal context pack for a worker."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]

try:
    from tools.validate import validate_work_item
except ModuleNotFoundError:  # pragma: no cover - exercised by direct CLI use
    sys.path.insert(0, str(ROOT))
    from tools.validate import validate_work_item


class DispatchError(ValueError):
    """A context pack cannot be safely dispatched."""


_SAFE_PATH = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?is)(?:PRIVATE_RAW|RESTRICTED|raw[_ -]?voice(?:[_ -]?body)?|"
    r"password|secret|api[_-]?key|private[_-]?key|credential)\s*[:=]\s*\S+"
)


def _error(detail: str, remediation: str) -> DispatchError:
    return DispatchError(f"dispatch: {detail}; remediation: {remediation}")


def _safe_context_path(value: object) -> bool:
    if not isinstance(value, str) or not _SAFE_PATH.fullmatch(value):
        return False
    return all(part not in {".", ".."} for part in value.split("/"))


def _require_list(value: object, field: str) -> list:
    if not isinstance(value, list):
        raise _error(f"{field} must be a list", f"declare {field} explicitly in the work item")
    return value


def _unique_sorted_strings(values: list, field: str) -> list[str]:
    if any(not isinstance(value, str) or not value for value in values):
        raise _error(f"{field} must contain non-empty strings", f"remove invalid entries from {field}")
    if any(_SENSITIVE_ASSIGNMENT.search(value) for value in values):
        raise _error(
            f"{field} contains a sensitive assignment",
            "pass policy text without raw values, credentials, or restricted data",
        )
    return sorted(set(values))


def _copy_recovery(source: Mapping[str, object]) -> dict:
    checkpoint = source.get("checkpoint", {})
    lease = source.get("lease", {})
    attempts = source.get("attempts", {})
    evidence = source.get("evidence", {})
    if not all(isinstance(value, dict) for value in (checkpoint, lease, attempts, evidence)):
        raise _error(
            "recovery state contains a non-object section",
            "provide validated checkpoint, lease, attempts, and evidence objects",
        )
    recovery = {
        "terminal_state": source.get("terminal_state"),
        "attempts": {
            "used": attempts.get("used"),
            "max": attempts.get("max"),
        },
        "lease": {
            key: lease[key]
            for key in ("status", "owner", "expires_at", "execution_id")
            if key in lease
        },
        "checkpoint": {
            key: checkpoint[key]
            for key in ("start_point", "next_action", "last_result", "decision", "execution_id")
            if key in checkpoint
        },
        "evidence": {
            key: list(evidence.get(key, []))
            for key in ("commits", "pull_requests", "tests", "changed_paths")
        },
    }
    for field in ("checkpoint", "lease"):
        serialized = json.dumps(recovery[field], ensure_ascii=False, sort_keys=True)
        if _SENSITIVE_ASSIGNMENT.search(serialized):
            raise _error(
                f"recovery.{field} contains a sensitive assignment",
                "remove sensitive values before dispatching recovery context",
            )
    return recovery


def load_context_files(work_item: dict, context_root: Path) -> dict[str, str]:
    """Read only the work item's required files without following paths outside root."""
    context = work_item.get("context", {})
    required_files = _require_list(context.get("required_files"), "context.required_files")
    root = context_root.resolve()
    contents: dict[str, str] = {}
    for relative in required_files:
        if not _safe_context_path(relative):
            raise _error(
                f"required file path is unsafe: {relative!r}",
                "use a relative path without dot segments or separators outside the workspace",
            )
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise _error(
                f"required file escapes context root: {relative!r}",
                "keep required files below the declared context root",
            ) from exc
        if not candidate.is_file():
            raise _error(
                f"required file is missing: {relative!r}",
                "restore the declared file or correct context.required_files",
            )
        try:
            contents[relative] = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise _error(
                f"required file is not UTF-8 text: {relative!r}",
                "dispatch text instructions and contracts only",
            ) from exc
    return contents


def build_context_pack(
    work_item: dict,
    file_contents: Mapping[str, str],
    rules: list[str] | None = None,
    recovery_state: Mapping[str, object] | None = None,
) -> dict:
    """Return only the fields a worker needs for one validated work item."""
    if not isinstance(work_item, dict):
        raise _error("work item must be an object", "load one validated work item")
    validation_errors = validate_work_item(work_item, f"dispatch:{work_item.get('id', '<unknown>')}")
    if validation_errors:
        raise _error(validation_errors[0], "repair the work item before dispatch")
    if not isinstance(file_contents, Mapping):
        raise _error("file_contents must be a mapping", "provide required file contents by relative path")

    context = work_item["context"]
    required_files = _require_list(context["required_files"], "context.required_files")
    if len(required_files) != len(set(required_files)):
        raise _error("context.required_files must be unique", "declare each context file once")
    files: list[dict[str, str]] = []
    for relative in sorted(required_files):
        if not _safe_context_path(relative):
            raise _error(
                f"required file path is unsafe: {relative!r}",
                "use a relative path without dot segments or separators outside the workspace",
            )
        if relative not in file_contents:
            raise _error(
                f"required file content is missing: {relative!r}",
                "load every context.required_files entry before dispatch",
            )
        content = file_contents[relative]
        if not isinstance(content, str):
            raise _error(
                f"required file content is not text: {relative!r}",
                "dispatch UTF-8 text only",
            )
        if _SENSITIVE_ASSIGNMENT.search(content):
            raise _error(
                f"required file contains a sensitive assignment: {relative!r}",
                "exclude raw/restricted data and credentials from the context pack",
            )
        files.append({"path": relative, "content": content})

    selected_rules = _unique_sorted_strings(rules or [], "rules")
    contracts = _unique_sorted_strings(_require_list(context["contracts"], "context.contracts"), "contracts")
    recovery_source = recovery_state if recovery_state is not None else work_item
    if not isinstance(recovery_source, Mapping):
        raise _error("recovery_state must be an object", "pass the persisted runtime state when resuming")

    task = {
        "id": work_item["id"],
        "title": work_item["title"],
        "owner_repository": work_item["owner_repository"],
        "target_repositories": sorted(work_item["target_repositories"]),
        "allowed_paths": sorted(work_item["allowed_paths"]),
        "depends_on": sorted(work_item["depends_on"]),
    }
    return {
        "version": 1,
        "task": task,
        "rules": selected_rules,
        "files": files,
        "contracts": contracts,
        "acceptance": work_item["acceptance"],
        "checks": work_item["checks"],
        "recovery": _copy_recovery(recovery_source),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a task-minimal worker context pack")
    parser.add_argument("--work-item", type=Path, required=True)
    parser.add_argument("--context-root", type=Path, default=ROOT)
    parser.add_argument("--recovery-state", type=Path, default=None)
    parser.add_argument("--rule", action="append", default=[])
    args = parser.parse_args()
    work_item_path = args.work_item if args.work_item.is_absolute() else Path.cwd() / args.work_item
    with work_item_path.open(encoding="utf-8") as handle:
        work_item = yaml.safe_load(handle)
    recovery_state = None
    if args.recovery_state is not None:
        recovery_path = args.recovery_state if args.recovery_state.is_absolute() else Path.cwd() / args.recovery_state
        with recovery_path.open(encoding="utf-8") as handle:
            recovery_state = yaml.safe_load(handle)
    try:
        pack = build_context_pack(
            work_item,
            load_context_files(work_item, args.context_root),
            args.rule,
            recovery_state,
        )
    except (OSError, DispatchError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(pack, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
