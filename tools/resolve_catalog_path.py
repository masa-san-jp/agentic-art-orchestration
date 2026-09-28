#!/usr/bin/env python3
"""Resolve historical public-catalog paths without changing execution evidence.

The registry is intentionally separate from ``execution/``.  A lookup follows
all aliases until it reaches a path that is not registered.  The same command
can emit read-only candidates from a local agentic-art-project Git history.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config/catalog-path-aliases.yaml"
PATH_PATTERN = re.compile(r"^plans/P[0-9]{4}-[A-Za-z0-9][A-Za-z0-9._-]*$")
PLAN_ID_PATTERN = re.compile(r"^P[0-9]{4}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")


class CatalogPathError(ValueError):
    """A registry or path cannot be resolved safely."""


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogPathError(f"REGISTRY_READ_FAILED: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CatalogPathError("REGISTRY_INVALID: expected a mapping")
    if value.get("contract_version") != "catalog-path-aliases/v1":
        raise CatalogPathError("REGISTRY_CONTRACT_UNSUPPORTED: expected catalog-path-aliases/v1")
    if value.get("source_repository") != "agentic-art-project":
        raise CatalogPathError("REGISTRY_SOURCE_UNSUPPORTED: expected agentic-art-project")
    aliases = value.get("aliases")
    if not isinstance(aliases, list):
        raise CatalogPathError("REGISTRY_INVALID: aliases must be a list")
    return value


def alias_map(registry: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for index, entry in enumerate(registry.get("aliases", [])):
        if not isinstance(entry, dict):
            raise CatalogPathError(f"REGISTRY_INVALID: aliases[{index}] must be an object")
        old_path = entry.get("old_path")
        new_path = entry.get("new_path")
        plan_id = entry.get("plan_id")
        commit = entry.get("rename_commit")
        reason = entry.get("reason")
        if not isinstance(old_path, str) or not PATH_PATTERN.fullmatch(old_path):
            raise CatalogPathError(f"REGISTRY_INVALID: aliases[{index}].old_path is not a catalog path")
        if not isinstance(new_path, str) or not PATH_PATTERN.fullmatch(new_path):
            raise CatalogPathError(f"REGISTRY_INVALID: aliases[{index}].new_path is not a catalog path")
        if old_path == new_path:
            raise CatalogPathError(f"REGISTRY_INVALID: aliases[{index}] maps a path to itself")
        if not isinstance(plan_id, str) or not PLAN_ID_PATTERN.fullmatch(plan_id):
            raise CatalogPathError(f"REGISTRY_INVALID: aliases[{index}].plan_id is invalid")
        if old_path.split("/", 2)[1].split("-", 1)[0] != plan_id:
            raise CatalogPathError(f"REGISTRY_INVALID: aliases[{index}].plan_id does not match old_path")
        if new_path.split("/", 2)[1].split("-", 1)[0] != plan_id:
            raise CatalogPathError(f"REGISTRY_INVALID: aliases[{index}].plan_id does not match new_path")
        if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
            raise CatalogPathError(f"REGISTRY_INVALID: aliases[{index}].rename_commit is invalid")
        if not isinstance(reason, str) or not reason.strip():
            raise CatalogPathError(f"REGISTRY_INVALID: aliases[{index}].reason is empty")
        if old_path in result:
            raise CatalogPathError(f"REGISTRY_DUPLICATE_OLD_PATH: {old_path}")
        result[old_path] = new_path
    return result


def resolve_path(path: str, registry: dict[str, Any] | None = None) -> str:
    """Return the terminal catalog path, or the same path if it was not renamed."""
    if not isinstance(path, str) or not PATH_PATTERN.fullmatch(path):
        raise CatalogPathError("INVALID_CATALOG_PATH: expected plans/P####-slug")
    mapping = alias_map(registry if registry is not None else load_registry())
    current = path
    seen: list[str] = []
    while current in mapping:
        if current in seen:
            cycle = " -> ".join(seen + [current])
            raise CatalogPathError(f"CATALOG_PATH_ALIAS_CYCLE: {cycle}")
        seen.append(current)
        current = mapping[current]
    return current


def validate_alias_cycles(registry: dict[str, Any]) -> list[str]:
    """Return all cycle errors without making a lookup fail halfway through."""
    mapping = alias_map(registry)
    errors: list[str] = []
    for start in mapping:
        current = start
        seen: list[str] = []
        while current in mapping:
            if current in seen:
                errors.append("CATALOG_PATH_ALIAS_CYCLE: " + " -> ".join(seen + [current]))
                break
            seen.append(current)
            current = mapping[current]
    return errors


def _plan_directory(path: str) -> tuple[str, str] | None:
    parts = path.split("/")
    if len(parts) < 3 or parts[0] != "plans":
        return None
    directory = "/".join(parts[:2])
    plan_id = parts[1].split("-", 1)[0]
    if not PLAN_ID_PATTERN.fullmatch(plan_id):
        return None
    return directory, plan_id


def history_candidates(project_root: Path, since: str) -> list[dict[str, str]]:
    """Extract deterministic directory-rename candidates after a commit ref."""
    project_root = project_root.resolve()
    if not (project_root / ".git").exists():
        raise CatalogPathError("PROJECT_NOT_GIT_REPOSITORY: --from-project-git must point to a Git checkout")
    try:
        subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--verify", f"{since}^{{commit}}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        result = subprocess.run(
            [
                "git", "-C", str(project_root), "log", "-M", "--name-status", "--format=@@%H",
                f"{since}..HEAD", "--", "plans",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()[-1:] or ["git command failed"]
        raise CatalogPathError(f"PROJECT_GIT_HISTORY_FAILED: {detail[0]}") from exc

    grouped: dict[tuple[str, str, str], set[str]] = {}
    commit = None
    for line in result.stdout.splitlines():
        if line.startswith("@@"):
            commit = line[2:].strip()
            continue
        if commit is None or not line.startswith("R"):
            continue
        fields = line.split("\t")
        if len(fields) < 3:
            fields = line.split(maxsplit=2)
        if len(fields) != 3:
            continue
        old_info = _plan_directory(fields[1])
        new_info = _plan_directory(fields[2])
        if old_info is None or new_info is None or old_info[0] == new_info[0] or old_info[1] != new_info[1]:
            continue
        key = (commit, old_info[0], new_info[0])
        grouped.setdefault(key, set()).add(fields[1])

    candidates = []
    for (commit, old_path, new_path), _files in sorted(grouped.items()):
        plan_id = old_path.split("/", 1)[1].split("-", 1)[0]
        candidates.append(
            {
                "old_path": old_path,
                "new_path": new_path,
                "plan_id": plan_id,
                "rename_commit": commit,
                "reason": "Directory rename detected from plans/ rename entries in Git history.",
            }
        )
    return candidates


def _print_candidates(candidates: list[dict[str, str]], output_format: str) -> None:
    value: dict[str, Any] = {
        "contract_version": "catalog-path-aliases/v1",
        "source_repository": "agentic-art-project",
        "candidates": candidates,
    }
    if output_format == "yaml":
        print(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), end="")
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_path", nargs="?", help="historical plans/P####-slug path")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--from-project-git", type=Path, help="emit alias candidates from a local Project checkout")
    parser.add_argument("--since", help="commit boundary; candidates are read from since..HEAD")
    parser.add_argument("--format", choices=("json", "yaml"), default="json", dest="output_format")
    args = parser.parse_args(argv)

    try:
        if args.from_project_git is not None:
            if args.old_path is not None or not args.since:
                parser.error("--from-project-git requires --since and no old_path")
            _print_candidates(history_candidates(args.from_project_git, args.since), args.output_format)
            return 0
        if args.old_path is None:
            parser.error("old_path is required unless --from-project-git is used")
        registry = load_registry(args.registry)
        print(resolve_path(args.old_path, registry))
        return 0
    except CatalogPathError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
