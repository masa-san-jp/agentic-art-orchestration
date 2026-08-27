#!/usr/bin/env python3
"""Qualify workspace HEAD pins before optionally adopting them in the parent manifest."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from tools.child_quality_gates import run_child_quality_gates
    from tools.production_exchange import run_exchange_e2e
    from tools.validate import load_yaml, validate_manifest
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.child_quality_gates import run_child_quality_gates
    from tools.production_exchange import run_exchange_e2e
    from tools.validate import load_yaml, validate_manifest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config" / "repositories.yaml"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
ID_LINE = re.compile(r"^  - id: ([a-z0-9]+(?:-[a-z0-9]+)*)\s*$")
PIN_LINE = re.compile(r"^(    observed_commit: )([0-9a-f]{40})(\s*)$")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def workspace_candidate(manifest: dict[str, Any], workspace_root: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Read clean workspace HEADs into a copy; never fetch, checkout, or mutate children."""
    candidate = copy.deepcopy(manifest)
    changes: list[dict[str, str]] = []
    errors: list[str] = []
    for repository in candidate.get("repositories", []):
        repository_id = repository["id"]
        checkout = workspace_root / repository["path"]
        head = _git(checkout, "rev-parse", "HEAD")
        if head.returncode != 0 or not SHA40.fullmatch(head.stdout.strip()):
            errors.append(f"{repository_id}: workspace HEAD unavailable")
            continue
        if _git(checkout, "status", "--porcelain").stdout.strip():
            errors.append(f"{repository_id}: workspace is dirty")
            continue
        new_commit = head.stdout.strip()
        old_commit = repository["observed_commit"]
        repository["observed_commit"] = new_commit
        if old_commit != new_commit:
            changes.append({"repository": repository_id, "old_commit": old_commit, "new_commit": new_commit})
    if errors:
        raise ValueError("pin qualification blocked: " + "; ".join(errors))
    return candidate, changes


def _manifest_hash(manifest: dict[str, Any]) -> str:
    rendered = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _replace_pins(path: Path, updates: dict[str, str]) -> None:
    """Apply only observed_commit lines, preserving the manifest's existing formatting."""
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    current_id: str | None = None
    applied: set[str] = set()
    rendered: list[str] = []
    for line in lines:
        id_match = ID_LINE.match(line.rstrip("\r\n"))
        if id_match:
            current_id = id_match.group(1)
        pin_match = PIN_LINE.match(line.rstrip("\r\n"))
        if current_id in updates and pin_match:
            newline = "\n" if line.endswith("\n") else ""
            rendered.append(f"{pin_match.group(1)}{updates[current_id]}{pin_match.group(3)}{newline}")
            applied.add(current_id)
        else:
            rendered.append(line)
    if applied != set(updates):
        missing = sorted(set(updates) - applied)
        raise ValueError(f"manifest pin lines not found: {missing}")
    path.write_text("".join(rendered), encoding="utf-8")


def apply_qualified_pins(
    manifest_path: Path,
    manifest: dict[str, Any],
    workspace_root: Path,
    report: dict[str, Any],
) -> str:
    """Adopt only the exact candidate that was independently qualified."""
    if report.get("status") != "PASSED":
        raise ValueError("pin update is not qualified; remediation: resolve child gates and exchange failures before --apply")
    current_candidate, current_changes = workspace_candidate(manifest, workspace_root)
    if _manifest_hash(current_candidate) != report.get("candidate_manifest_hash") or current_changes != report.get("changes"):
        raise ValueError("pin candidate changed after qualification; remediation: rerun read-only qualification before --apply")
    updates = {item["repository"]: item["new_commit"] for item in current_changes}
    _replace_pins(manifest_path, updates)
    return _manifest_hash(current_candidate)


def qualify_pin_update(
    manifest: dict[str, Any],
    workspace_root: Path,
    *,
    timeout_seconds: int = 60,
    run_id: str = "pin-update-qualification",
    child_python: str = sys.executable,
    python_root: Path | None = None,
) -> dict[str, Any]:
    candidate, changes = workspace_candidate(manifest, workspace_root)
    manifest_errors = validate_manifest(candidate, "pin-candidate")
    if manifest_errors:
        raise ValueError("pin candidate is invalid: " + " | ".join(manifest_errors[:5]))
    quality = run_child_quality_gates(
        candidate,
        workspace_root,
        timeout_seconds,
        f"{run_id}:child-gates",
        python_root=python_root,
    )
    gate_statuses = {result["status"] for result in quality["results"]}
    exchange: dict[str, Any] = {"status": "NOT_RUN", "reason": "child quality gates did not pass"}
    if not gate_statuses or gate_statuses == {"PASSED"}:
        with tempfile.TemporaryDirectory(prefix="pin-update-exchange-") as temporary:
            exchange = run_exchange_e2e(
                candidate,
                workspace_root,
                Path(temporary),
                run_id=f"{run_id}:exchange",
                generated_at="2026-08-14T00:00:00+09:00",
                child_python=child_python,
            )
    status = "PASSED" if gate_statuses == {"PASSED"} and exchange.get("status") == "PASSED" else "BLOCKED" if "BLOCKED" in gate_statuses or exchange.get("status") == "BLOCKED" else "FAILED"
    child_status = "FAILED" if gate_statuses & {"FAILED", "ENV_UNSATISFIED"} else "BLOCKED" if "BLOCKED" in gate_statuses else "PASSED"
    return {
        "contract_version": "pin-update-qualification/v1",
        "status": status,
        "manifest_hash": _manifest_hash(manifest),
        "candidate_manifest_hash": _manifest_hash(candidate),
        "changes": changes,
        "child_quality_gates": {"status": child_status, "repository_count": len(quality["results"])},
        "production_exchange": {"status": exchange.get("status", "BLOCKED")},
        "applied": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--run-id", default="pin-update-qualification")
    parser.add_argument("--child-python", default=sys.executable)
    parser.add_argument(
        "--python-root",
        type=Path,
        help="optional root of pre-provisioned per-child environments; no installation is performed",
    )
    parser.add_argument("--apply", action="store_true", help="adopt qualified workspace HEADs in the parent manifest")
    args = parser.parse_args()
    try:
        manifest = load_yaml(args.manifest)
        manifest_errors = validate_manifest(manifest, str(args.manifest))
        if manifest_errors:
            raise ValueError("\n".join(manifest_errors))
        python_root = args.python_root
        if python_root is not None and not python_root.is_absolute():
            python_root = Path.cwd() / python_root
        report = qualify_pin_update(
            manifest,
            args.workspace_root,
            timeout_seconds=args.timeout,
            run_id=args.run_id,
            child_python=args.child_python,
            python_root=python_root,
        )
        if args.apply:
            manifest_hash_after = apply_qualified_pins(args.manifest, manifest, args.workspace_root, report)
            report["applied"] = True
            report["manifest_hash_after"] = manifest_hash_after
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"command": "qualify-pin-update", "status": report["status"], "changed_pins": len(report["changes"]), "applied": report["applied"]}, sort_keys=True))
        return 0 if report["status"] == "PASSED" else 2
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
