#!/usr/bin/env python3
"""Run child quality gates from immutable manifest-pinned commit archives."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

try:
    from tools.quality_gates import _gate_result, _run_gate
    from tools.validate import (
        ROOT,
        load_yaml,
        validate_child_quality_gates,
        validate_manifest,
    )
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.quality_gates import _gate_result, _run_gate
    from tools.validate import ROOT, load_yaml, validate_child_quality_gates, validate_manifest


DEFAULT_MANIFEST = ROOT / "config/repositories.yaml"
DEFAULT_WORKSPACE_ROOT = ROOT / "repos"
DEFAULT_OUTPUT = ROOT / "data/child-quality-gates.json"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _workspace_state(root: Path, observed_commit: str) -> tuple[str, str | None]:
    if not root.is_dir():
        return "MISSING", None
    head = _git(root, "rev-parse", "HEAD")
    if head.returncode != 0:
        return "UNKNOWN", None
    workspace_commit = head.stdout.strip()
    dirty = _git(root, "status", "--porcelain").stdout.strip()
    if dirty:
        state = "DIRTY"
    elif workspace_commit == observed_commit:
        state = "MATCHED"
    else:
        state = "STALE"
    return state, workspace_commit


def _not_run(command: str, error: str) -> dict:
    return _gate_result(command, "NOT_RUN", None, 0, error=error)


def _extract_archive(root: Path, commit: str, target: Path) -> str | None:
    raw = subprocess.run(
        ["git", "-C", str(root), "archive", "--format=tar", commit],
        capture_output=True,
        check=False,
    )
    if raw.returncode != 0:
        detail = raw.stderr.decode("utf-8", errors="replace").strip() or "git archive returned non-zero"
        return f"observed commit archive unavailable: {detail}; remediation: fetch or pin the observed immutable commit"
    try:
        with tarfile.open(fileobj=io.BytesIO(raw.stdout), mode="r:") as bundle:
            members = bundle.getmembers()
            for member in members:
                member_path = Path(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    return "observed archive contains an unsafe path; remediation: reject the child archive before execution"
            for member in members:
                bundle.extract(member, target)
    except (OSError, tarfile.TarError) as exc:
        return f"observed commit archive extraction failed: {exc}; remediation: reject the child archive before execution"
    return None


def _validate_gate_manifest(manifest: dict) -> list[str]:
    """Validate the subset of the parent manifest needed by this runner."""
    errors: list[str] = []
    repositories = manifest.get("repositories") if isinstance(manifest, dict) else None
    if not isinstance(repositories, list) or not repositories:
        return ["manifest.repositories must be a non-empty list; remediation: declare child repositories in config/repositories.yaml"]
    seen: set[str] = set()
    for index, repository in enumerate(repositories):
        prefix = f"manifest.repositories[{index}]"
        if not isinstance(repository, dict):
            errors.append(f"{prefix} must be an object; remediation: preserve the repository manifest shape")
            continue
        repository_id = repository.get("id")
        if not isinstance(repository_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", repository_id):
            errors.append(f"{prefix}.id is invalid; remediation: use a stable kebab-case repository ID")
        elif repository_id in seen:
            errors.append(f"{prefix}.id duplicates {repository_id!r}; remediation: use one manifest entry per child repository")
        else:
            seen.add(repository_id)
        repository_path = repository.get("path")
        if (
            not isinstance(repository_path, str)
            or not repository_path
            or Path(repository_path).is_absolute()
            or ".." in Path(repository_path).parts
        ):
            errors.append(f"{prefix}.path is invalid; remediation: declare a relative child checkout path")
        observed_commit = repository.get("observed_commit")
        if not isinstance(observed_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", observed_commit):
            errors.append(f"{prefix}.observed_commit is not a 40-character commit; remediation: pin an immutable observed commit")
        commands = repository.get("quality_gates")
        if not isinstance(commands, list) or not commands or any(not isinstance(command, str) or not command.strip() for command in commands):
            errors.append(f"{prefix}.quality_gates is invalid; remediation: declare one or more executable quality gate commands")
    return errors


def _run_repository(repository: dict, workspace_root: Path, timeout_seconds: int) -> dict:
    repository_id = repository["id"]
    observed_commit = repository["observed_commit"]
    root = workspace_root / repository["path"]
    workspace_state, workspace_commit = _workspace_state(root, observed_commit)
    commands = repository["quality_gates"]
    quality_gate_hash = sha256_hex(commands)
    if not root.is_dir() or workspace_commit is None:
        error = "child workspace is missing or not a Git checkout; remediation: initialize the workspace before running immutable gates"
        return {
            "repository": repository_id,
            "observed_commit": observed_commit,
            "workspace_commit": workspace_commit,
            "workspace_state": workspace_state,
            "execution_mode": "NOT_RUN",
            "quality_gate_hash": quality_gate_hash,
            "status": "BLOCKED",
            "gates": [_not_run(command, error) for command in commands],
        }
    with tempfile.TemporaryDirectory(prefix=f"child-gate-{repository_id}-") as temporary:
        target = Path(temporary)
        archive_error = _extract_archive(root, observed_commit, target)
        if archive_error:
            return {
                "repository": repository_id,
                "observed_commit": observed_commit,
                "workspace_commit": workspace_commit,
                "workspace_state": workspace_state,
                "execution_mode": "NOT_RUN",
                "quality_gate_hash": quality_gate_hash,
                "status": "BLOCKED",
                "gates": [_not_run(command, archive_error) for command in commands],
            }
        gates = [_run_gate(command, target, timeout_seconds) for command in commands]
        return {
            "repository": repository_id,
            "observed_commit": observed_commit,
            "workspace_commit": workspace_commit,
            "workspace_state": workspace_state,
            "execution_mode": "immutable-archive",
            "quality_gate_hash": quality_gate_hash,
            "status": "FAILED" if any(gate["status"] == "FAILED" for gate in gates) else "PASSED",
            "gates": gates,
        }


def run_child_quality_gates(
    manifest: dict,
    workspace_root: Path,
    timeout_seconds: int = 60,
    run_id: str = "v12-child-gates",
) -> dict:
    """Execute every manifest gate only from its exact observed commit archive."""
    manifest_errors = _validate_gate_manifest(manifest)
    if manifest_errors:
        raise ValueError("\n".join(manifest_errors))
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive; remediation: use a finite positive timeout")
    results = [
        _run_repository(repository, workspace_root, timeout_seconds)
        for repository in sorted(manifest["repositories"], key=lambda item: item["id"])
    ]
    report = {
        "contract_version": "child-quality-gates/v1",
        "run_id": run_id,
        "manifest_hash": sha256_hex(manifest),
        "repository_count": len(results),
        "results": results,
    }
    errors = validate_child_quality_gates(report, "child-quality-gates")
    if errors:
        raise ValueError("\n".join(errors))
    return report


def _render(data: dict) -> bytes:
    return (canonical_json(data) + "\n").encode("utf-8")


def _deterministic_view(value: object) -> object:
    """Remove runtime-only measurements before comparing generated evidence."""
    if isinstance(value, dict):
        return {
            key: _deterministic_view(item)
            for key, item in value.items()
            if key != "duration_ms"
        }
    if isinstance(value, list):
        return [_deterministic_view(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run manifest child gates from immutable observed commits")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--run-id", default="v12-child-gates")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="compare generated bytes without writing")
    args = parser.parse_args()
    try:
        manifest = load_yaml(args.manifest)
        manifest_errors = validate_manifest(manifest, str(args.manifest))
        if manifest_errors:
            raise ValueError("\n".join(manifest_errors))
        report = run_child_quality_gates(manifest, args.workspace_root, args.timeout, args.run_id)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rendered = _render(report)
    if args.check:
        try:
            observed = args.output.read_bytes()
        except OSError as exc:
            print(f"ERROR: {args.output}: {exc}; remediation: generate child gate evidence first", file=sys.stderr)
            return 1
        try:
            observed_data = json.loads(observed)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"ERROR: {args.output}: stored child gate evidence is not valid JSON: {exc}; remediation: regenerate immutable gate evidence", file=sys.stderr)
            return 1
        if _deterministic_view(observed_data) != _deterministic_view(report):
            print(f"ERROR: {args.output}: generated child gate evidence differs beyond runtime-only duration; remediation: regenerate immutable gate evidence", file=sys.stderr)
            return 1
        changed = False
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        changed = args.output.exists() and args.output.read_bytes() == rendered
        if not changed:
            args.output.write_bytes(rendered)
    statuses = {result["status"] for result in report["results"]}
    overall_status = "FAILED" if "FAILED" in statuses else "BLOCKED" if "BLOCKED" in statuses else "PASSED"
    print(json.dumps({"changed": not changed if not args.check else False, "command": "child-quality-gates", "repository_count": report["repository_count"], "status": overall_status}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
