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
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
# The pin is not one line. Measured 2026-08-20: the same commit is repeated in
# the manifest, eleven test fixtures, the retrieval index, a test module and the
# handoff record. Changing only the manifest leaves the retrieval index and the
# improvement loop rejecting their own base commit.
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


def evaluate(root: Path, workspace_root: Path, timeout_seconds: int | None = None) -> dict:
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


def apply_report(root: Path, report: dict) -> list[str]:
    if report["status"] != "READY":
        raise PinAdoptError(f"pins are not adoptable: status is {report['status']}")
    written: list[str] = []
    for item in report["repositories"]:
        if not item["adoptable"]:
            continue
        for relative in item["occurrences"]:
            path = root / relative
            text = path.read_text(encoding="utf-8")
            updated = text.replace(item["current_pin"], item["candidate_commit"])
            if updated != text:
                path.write_text(updated, encoding="utf-8")
                written.append(relative)
    return sorted(set(written))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report or adopt child repository pins.")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--apply", action="store_true", help="write the pins when every check passed")
    parser.add_argument("--workspace-root", type=Path, default=ROOT / "repos")
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.dry_run == args.apply:
        parser.error("choose exactly one of --dry-run and --apply")

    root = args.root.resolve()
    try:
        report = evaluate(root, args.workspace_root.resolve(), args.timeout)
        if args.apply:
            report["written_files"] = apply_report(root, report)
    except (PinAdoptError, OSError, KeyError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
