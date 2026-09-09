#!/usr/bin/env python3
"""Resolve the explicit Project-owned repo-local workspace contract (v2)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping

from tools.validate import _schema_errors, load_json

ROOT = Path(__file__).resolve().parents[1]
V2_SCHEMA = ROOT / "schemas/output-destinations-v2.schema.json"
RESOLUTION_SCHEMA = ROOT / "schemas/destination-resolution-v2.schema.json"
ENVIRONMENT = "AGENTIC_ART_PROJECT_ROOT"
ID_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-")


class RepoLocalDestinationError(ValueError):
    pass


def _absolute(value: object, label: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value) or "\x00" in str(value):
        raise RepoLocalDestinationError(f"{label}: PROJECT_ROOT_REQUIRED")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RepoLocalDestinationError(f"{label}: PROJECT_ROOT_REQUIRED")
    if path.is_symlink():
        raise RepoLocalDestinationError("UNSAFE_LOCAL_WORKSPACE: project root is a symlink")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepoLocalDestinationError("PROJECT_ROOT_REQUIRED: project root is not readable") from exc
    if not resolved.is_dir() or resolved == ROOT or ROOT in resolved.parents:
        raise RepoLocalDestinationError("UNSAFE_LOCAL_WORKSPACE: choose a regular Project checkout outside Orchestration")
    return resolved


def _git(root: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, env=env)
    if result.returncode:
        raise RepoLocalDestinationError("UNSAFE_LOCAL_WORKSPACE: Project is not a Git worktree")
    return result.stdout.strip()


def _safe_id(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if label == "project_id":
        parts = value.split("/") if isinstance(value, str) else []
        if not parts or len(parts) > 4 or any(not part or len(part) > 128 or any(c not in ID_CHARS for c in part) for part in parts):
            raise RepoLocalDestinationError(f"{label}: unsafe identifier")
        return value
    if not isinstance(value, str) or not value or len(value) > 128 or any(c not in ID_CHARS for c in value):
        raise RepoLocalDestinationError(f"{label}: unsafe identifier")
    return value


def _checks(root: Path) -> dict[str, str]:
    if _git(root, "rev-parse", "--show-toplevel") != str(root):
        raise RepoLocalDestinationError("UNSAFE_LOCAL_WORKSPACE: Project root is not the worktree root")
    if not (root / "public-project.yaml").is_file():
        raise RepoLocalDestinationError("PROJECT_LAYOUT_INCOMPATIBLE: public-project.yaml is missing")
    # The owner validator is the authority for the Project layout and local contract.
    validate = root / "tools" / "validate.py"
    if not validate.is_file():
        raise RepoLocalDestinationError("PROJECT_LAYOUT_INCOMPATIBLE: Project validator is missing")
    checked = subprocess.run([os.environ.get("PYTHON", sys.executable), str(validate), "--check", "--root", str(root)], cwd=root, text=True, capture_output=True)
    if checked.returncode:
        raise RepoLocalDestinationError("PROJECT_LAYOUT_INCOMPATIBLE: Project validator failed")
    ignore = subprocess.run(["git", "check-ignore", "-q", "--no-index", ".agentic-art/probe"], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if ignore.returncode:
        raise RepoLocalDestinationError("PRIVATE_ROOT_NOT_IGNORED: Project must ignore /.agentic-art/")
    tracked = _git(root, "ls-files", "--", ".agentic-art")
    if tracked:
        raise RepoLocalDestinationError("PRIVATE_PATH_TRACKED: .agentic-art contains tracked files")
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise RepoLocalDestinationError("PROJECT_TRACKED_DIRTY: clean tracked Project checkout is required")
    for relative in (".agentic-art", ".agentic-art/config.yaml", ".agentic-art/state", ".agentic-art/internal", ".agentic-art/staging"):
        candidate = root / relative
        if os.path.lexists(candidate) and candidate.is_symlink():
            raise RepoLocalDestinationError("UNSAFE_LOCAL_WORKSPACE: fixed workspace path is a symlink")
        if relative != ".agentic-art/config.yaml" and os.path.lexists(candidate) and not candidate.is_dir():
            raise RepoLocalDestinationError("UNSAFE_LOCAL_WORKSPACE: fixed workspace path is not a directory")
        if relative == ".agentic-art/config.yaml" and os.path.lexists(candidate) and not candidate.is_file():
            raise RepoLocalDestinationError("UNSAFE_LOCAL_WORKSPACE: config path is not a file")
    return {"project_git_root": "PASS", "ignore": "PASS", "tracked_private": "PASS", "symlinks": "PASS", "tracked_status": "CLEAN"}


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def resolve_project_root(project_root: str | Path | None = None, *, environment: Mapping[str, str] | None = None, run_id: str | None = None, project_id: str | None = None) -> dict[str, object]:
    """Resolve a Project checkout before creating any private workspace bytes."""
    env = os.environ if environment is None else environment
    if project_root is not None and ENVIRONMENT in env:
        raise RepoLocalDestinationError("AMBIGUOUS_DESTINATION_MODE: --project-root and AGENTIC_ART_PROJECT_ROOT both selected")
    source = "direct-cli" if project_root is not None else "environment"
    selected = project_root if project_root is not None else env.get(ENVIRONMENT)
    if selected is None:
        raise RepoLocalDestinationError("PROJECT_ROOT_REQUIRED: pass --project-root or AGENTIC_ART_PROJECT_ROOT")
    root = _absolute(selected, "project_root")
    checks = _checks(root)
    commit = _git(root, "rev-parse", "HEAD")
    paths = {
        "state_root": (".agentic-art/state", root / ".agentic-art/state"),
        "internal_output_root": (".agentic-art/internal", root / ".agentic-art/internal"),
        "staging_root": (".agentic-art/staging", root / ".agentic-art/staging"),
        "public_projection_root": (".", root),
    }
    destinations = {key: {"path": str(path), "relative": rel, "source": "repo-local-derived"} for key, (rel, path) in paths.items()}
    config = {"contract_version": "output-destinations/v2", "mode": "repo-local-project", "project_root": str(root), "destinations": {key: rel for key, (rel, _) in paths.items()}}
    resolution = {
        "contract_version": "destination-resolution/v2", "mode": "repo-local-project", "project_root": str(root), "source": source,
        "project_code_commit": commit, "project_layout_contract": "repo-local-project-workspace/v1", "destinations": destinations,
        "checks": checks, "run_id": _safe_id(run_id, "run_id"), "project_id": _safe_id(project_id, "project_id"),
        "classification": "PROJECT_INTERNAL", "config_sha256": hashlib.sha256(_canonical(config)).hexdigest(),
    }
    errors = _schema_errors(resolution, load_json(RESOLUTION_SCHEMA), "destination-resolution/v2")
    if errors:
        raise RepoLocalDestinationError("RESOLUTION_INVALID: " + " | ".join(errors))
    return resolution


def validate_resolution(value: object) -> list[str]:
    return _schema_errors(value, load_json(RESOLUTION_SCHEMA), "destination-resolution/v2")


def write_resolution_evidence(project_root: str | Path, run_id: str, resolution: Mapping[str, object]) -> Path:
    errors = validate_resolution(resolution)
    if errors:
        raise RepoLocalDestinationError("RESOLUTION_INVALID: " + " | ".join(errors))
    if not run_id or any(c not in ID_CHARS for c in run_id):
        raise RepoLocalDestinationError("UNSAFE_LOCAL_WORKSPACE: unsafe run ID")
    target = Path(project_root).resolve() / ".agentic-art" / "state" / run_id / "destination-resolution.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(dict(resolution), ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if target.exists():
        if target.is_file() and target.read_bytes() == data:
            return target
        raise RepoLocalDestinationError("RESOLUTION_CONFLICT: existing evidence differs")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.link(temporary, target)
    except FileExistsError:
        if target.read_bytes() != data:
            raise RepoLocalDestinationError("RESOLUTION_CONFLICT: concurrent evidence differs")
    finally:
        try: temporary.unlink()
        except FileNotFoundError: pass
    return target
