#!/usr/bin/env python3
"""Move the pins forward, once the commits they would move to have been checked.

    python3 tools/pin_adopt.py --dry-run
    python3 tools/pin_adopt.py --apply

The drift was already detected: startup reports `remote_update_candidate`
every session. Nothing could act on it, because no code in this repository
writes `observed_commit`, and the runbook says three times not to update the
pins without saying anywhere how. So the pins sat still while the children
moved, and the boundary broke where nobody was looking.

Checking is automatic. Writing is not: the manifest is a human gate here and
that is left alone. `--apply` writes only when every check passed, and never
part of the way.
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:  # pragma: no cover - direct CLI use
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.child_quality_gates import run_child_quality_gates
from tools.validate import ROOT, load_yaml

MANIFEST_PATH = ROOT / "config/repositories.yaml"
DEFAULT_OUTPUT = ROOT / "data/pin-adoption.json"
PIN_ADOPTION_SCOPE_PATH = ROOT / "config/pin-adoption-scope.yaml"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
# The pin is not one line. Measured 2026-08-20: the same commit is repeated in
# the manifest, eleven test fixtures, the retrieval index, a test module and the
# handoff record. Changing only the manifest leaves the retrieval index and the
# improvement loop rejecting their own base commit.
#
# Not every one of those repetitions is the same kind of thing, though.
# config/repositories.yaml and tests/fixtures/** describe the CURRENT pin;
# execution/ (and, as Issue 261 found, a narrative doc like
# docs/aak-02-execution.md) describe what a past run actually observed at the
# time it ran. Rewriting the second kind after the fact makes the record
# claim an observation that never happened. `occurrences()` below still finds
# every repetition, because the report needs to show all of them; only
# `apply_report()` decides which ones to write, using the allowlist in
# config/pin-adoption-scope.yaml.
SEARCHED_SUFFIXES = {".json", ".yaml", ".yml", ".py", ".md"}
SKIPPED_PREFIXES = ("data/", ".git/", ".venv/", "repos/")


class PinAdoptError(ValueError):
    """The adoption cannot be decided or carried out."""


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _candidate(workspace_root: Path, repository: dict) -> dict:
    path = workspace_root / repository["path"]
    if not path.is_dir():
        return {"head": None, "reason": "child checkout is missing"}
    head = _git(path, "rev-parse", "HEAD")
    if not COMMIT_PATTERN.fullmatch(head):
        return {"head": None, "reason": "child checkout has no readable HEAD"}
    dirty = _git(path, "status", "--porcelain")
    if dirty:
        return {"head": head, "reason": "child checkout has uncommitted changes"}
    behind = _git(path, "rev-list", "--count", f"{head}..origin/main")
    if behind and behind != "0":
        return {"head": head, "reason": f"child checkout is {behind} commit(s) behind its remote"}
    ahead = _git(path, "rev-list", "--count", f"{repository['observed_commit']}..{head}")
    return {"head": head, "reason": None, "commits_ahead": int(ahead or 0)}


def occurrences(root: Path, commit: str) -> list[str]:
    """Every tracked file that repeats this commit, because the pin is not one line."""
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if not path.is_file() or path.suffix not in SEARCHED_SUFFIXES:
            continue
        if any(relative.startswith(prefix) for prefix in SKIPPED_PREFIXES):
            continue
        try:
            if commit in path.read_text(encoding="utf-8"):
                found.append(relative)
        except (OSError, UnicodeDecodeError):
            continue
    return found


def evaluate(
    root: Path,
    workspace_root: Path,
    timeout_seconds: int | None = None,
    python_root: Path | None = None,
) -> dict:
    manifest = load_yaml(MANIFEST_PATH)
    repositories = manifest["repositories"]
    candidates: dict[str, dict] = {}
    for repository in repositories:
        candidates[repository["id"]] = _candidate(workspace_root, repository)

    trial = copy.deepcopy(manifest)
    for repository in trial["repositories"]:
        candidate = candidates[repository["id"]]
        if candidate.get("head") and not candidate.get("reason"):
            repository["observed_commit"] = candidate["head"]

    kwargs = {"run_id": "pin-adopt"}
    if timeout_seconds is not None:
        kwargs["timeout_seconds"] = timeout_seconds
    if python_root is not None:
        kwargs["python_root"] = python_root
    gates = run_child_quality_gates(trial, workspace_root, **kwargs)
    gate_status = {item["repository"]: item["status"] for item in gates["results"]}

    repositories_report = []
    for repository in repositories:
        identifier = repository["id"]
        candidate = candidates[identifier]
        status = gate_status.get(identifier, "NOT_RUN")
        reason = candidate.get("reason")
        head = candidate.get("head")
        if reason:
            adoptable = False
        elif head == repository["observed_commit"]:
            adoptable = False
            reason = "already at the candidate commit"
        elif status != "PASSED":
            adoptable = False
            reason = f"child quality gates are {status} at the candidate commit"
        else:
            adoptable = True
        repositories_report.append({
            "repository": identifier,
            "current_pin": repository["observed_commit"],
            "candidate_commit": head,
            "commits_ahead": candidate.get("commits_ahead", 0),
            "child_gate_status": status,
            "adoptable": adoptable,
            "reason": reason,
            "occurrences": occurrences(root, repository["observed_commit"]) if adoptable else [],
        })

    movable = [item for item in repositories_report if item["adoptable"]]
    blocked = [item for item in repositories_report if not item["adoptable"] and item["commits_ahead"]]
    return {
        "contract_version": "pin-adoption/v1",
        "workspace_root": str(workspace_root),
        "repositories": repositories_report,
        "adoptable_count": len(movable),
        "blocked_count": len(blocked),
        # Partial adoption would leave the manifest describing a workspace that
        # never existed as a whole, so the decision is taken over the whole set.
        "status": "BLOCKED" if blocked else ("READY" if movable else "UNCHANGED"),
    }


def rewritable_globs(scope_path: Path = PIN_ADOPTION_SCOPE_PATH) -> list[str]:
    """The allowlist of path globs that represent the current pin.

    An allowlist, not a denylist keyed on `execution/`: a denylist would have
    missed docs/aak-02-execution.md, a historical record that lives outside
    execution/ and was found rewritten in the Issue 261 incident. An
    allowlist only ever rewrites a path it explicitly names.
    """
    if not scope_path.is_file():
        raise PinAdoptError(f"{scope_path}: rewrite-scope allowlist is missing")
    scope = load_yaml(scope_path)
    paths = scope.get("rewritable_paths") if isinstance(scope, dict) else None
    if not isinstance(paths, list) or not paths:
        raise PinAdoptError(f"{scope_path}: rewritable_paths is missing or empty")
    return paths


def _is_rewritable(relative: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) for pattern in globs)


def apply_report(root: Path, report: dict) -> tuple[list[str], list[str]]:
    """Write only occurrences inside the rewrite-scope allowlist.

    Returns `(written_files, preserved_occurrences)`. An occurrence outside
    the allowlist -- most importantly anything under execution/, a historical
    record of what a past run actually observed -- is never opened for
    writing and is reported back as preserved, not silently dropped.
    """
    if report["status"] != "READY":
        raise PinAdoptError(f"pins are not adoptable: status is {report['status']}")
    globs = rewritable_globs()
    written: list[str] = []
    preserved: list[str] = []
    for item in report["repositories"]:
        if not item["adoptable"]:
            continue
        for relative in item["occurrences"]:
            if not _is_rewritable(relative, globs):
                preserved.append(relative)
                continue
            path = root / relative
            text = path.read_text(encoding="utf-8")
            updated = text.replace(item["current_pin"], item["candidate_commit"])
            if updated != text:
                path.write_text(updated, encoding="utf-8")
                written.append(relative)
    return sorted(set(written)), sorted(set(preserved))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report or adopt child repository pins.")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--apply", action="store_true", help="write the pins when every check passed")
    parser.add_argument("--workspace-root", type=Path, default=ROOT / "repos")
    parser.add_argument(
        "--python-root",
        type=Path,
        help="optional root of pre-provisioned per-child environments; no installation is performed",
    )
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.dry_run == args.apply:
        parser.error("choose exactly one of --dry-run and --apply")

    root = args.root.resolve()
    python_root = args.python_root
    if python_root is not None and not python_root.is_absolute():
        python_root = Path.cwd() / python_root
    try:
        report = evaluate(root, args.workspace_root.resolve(), args.timeout, python_root)
        if args.apply:
            written, preserved = apply_report(root, report)
            report["written_files"] = written
            report["preserved_occurrences"] = preserved
    except (PinAdoptError, OSError, KeyError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
