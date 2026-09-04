#!/usr/bin/env python3
"""Manage independent repository checkouts declared by repositories.yaml."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from validate import (  # noqa: E402
    _schema_errors,
    load_json,
    load_yaml,
    validate_manifest,
    validate_workspace_bootstrap_contract,
)


DEFAULT_MANIFEST = ROOT / "config/repositories.yaml"
DEFAULT_OFFLINE_FIXTURE_ROOT = Path(tempfile.gettempdir()) / "agentic-art-orchestration-offline-fixture"
WORKSPACE_BOOTSTRAP_SCHEMA = ROOT / "schemas/workspace-bootstrap.schema.json"
BOOTSTRAP_STATUS_EXIT_CODES = {
    "READY": 0,
    "BLOCKED_PIN_DRIFT": 2,
    "BLOCKED_EXISTING_WORKSPACE": 2,
    "BLOCKED_REMOTE_ACCESS": 2,
    "BLOCKED_RACE": 2,
    "FAILED": 1,
}
BOOTSTRAP_LOCK_NAME = ".agentic-art-bootstrap.lock"
BOOTSTRAP_FINDING_CODES = {
    "missing": "MISSING",
    "non-directory": "NON_DIRECTORY",
    "invalid-checkout": "INVALID_CHECKOUT",
    "repository-mismatch": "REPOSITORY_MISMATCH",
    "remote-mismatch": "REMOTE_MISMATCH",
    "dirty": "DIRTY",
    "untracked": "UNTRACKED",
    "detached": "DETACHED",
    "upstream-missing": "UPSTREAM_MISSING",
    "upstream-invalid": "UPSTREAM_INVALID",
    "unpushed": "AHEAD",
    "behind": "BEHIND",
    "diverged": "DIVERGED",
    "remote-access": "REMOTE_ACCESS",
    "race": "RACE",
    "not-run": "NOT_RUN",
    "pin-drift": "PIN_DRIFT",
}
BOOTSTRAP_FINDING_ORDER = tuple(dict.fromkeys(BOOTSTRAP_FINDING_CODES.values()))


class WorkspaceError(RuntimeError):
    """A recoverable workspace precondition or Git operation failure."""


def run_git(args: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no Git error output"
        location = f" in {cwd}" if cwd else ""
        raise WorkspaceError(f"git {' '.join(args)} failed{location}: {detail}")
    return result.stdout.strip()


def run_git_optional(
    args: list[str], cwd: Path | None, env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    data = load_yaml(path)
    errors = validate_manifest(data, str(path.relative_to(ROOT)))
    if errors:
        raise WorkspaceError("manifest validation failed:\n" + "\n".join(f"- {error}" for error in errors))
    return data


def resolve_path(value: str | Path, base: Path = ROOT) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def resolve_workspace_root(manifest: dict, override: str | None) -> Path:
    return resolve_path(override or manifest["workspace_root"])


def fixture_remote_root(fixture_root: Path) -> Path:
    return fixture_root / "remotes"


def _fixture_commit_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "offline-fixture",
            "GIT_AUTHOR_EMAIL": "offline-fixture@example.invalid",
            "GIT_COMMITTER_NAME": "offline-fixture",
            "GIT_COMMITTER_EMAIL": "offline-fixture@example.invalid",
        }
    )
    return env


def ensure_offline_remotes(manifest: dict, fixture_root: Path) -> tuple[Path, bool]:
    fixture_root.mkdir(parents=True, exist_ok=True)
    remotes = fixture_remote_root(fixture_root)
    remotes.mkdir(parents=True, exist_ok=True)
    created = False

    for repository in manifest["repositories"]:
        remote = remotes / f"{repository['id']}.git"
        if remote.exists():
            is_bare = run_git(["rev-parse", "--is-bare-repository"], cwd=remote)
            if is_bare != "true":
                raise WorkspaceError(
                    f"offline fixture remote {remote} is not a bare repository; "
                    "remediation: remove only that fixture remote and retry"
                )
            continue

        staging_root = Path(tempfile.mkdtemp(prefix="fixture-", dir=fixture_root))
        try:
            seed = staging_root / "seed"
            staged_remote = staging_root / f"{repository['id']}.git"
            default_branch = repository["default_branch"]
            run_git(["init", "-b", default_branch, str(seed)])
            (seed / "README.md").write_text(
                f"Synthetic offline fixture for {repository['id']}\n",
                encoding="utf-8",
            )
            (seed / "fixture-repository-id.txt").write_text(
                f"{repository['id']}\n",
                encoding="utf-8",
            )
            run_git(["add", "README.md", "fixture-repository-id.txt"], cwd=seed)
            run_git(
                [
                    "-c",
                    "user.name=offline-fixture",
                    "-c",
                    "user.email=offline-fixture@example.invalid",
                    "commit",
                    "-m",
                    "Create offline fixture",
                ],
                cwd=seed,
                env=_fixture_commit_env(),
            )
            run_git(["init", "--bare", str(staged_remote)])
            run_git(["remote", "add", "origin", str(staged_remote)], cwd=seed)
            run_git(["push", "origin", default_branch], cwd=seed)
            run_git(["symbolic-ref", "HEAD", f"refs/heads/{default_branch}"], cwd=staged_remote)
            os.replace(staged_remote, remote)
            created = True
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)
    return remotes, created


def expected_remote(repository: dict, offline_remotes: Path | None) -> str:
    if offline_remotes is not None:
        return str((offline_remotes / f"{repository['id']}.git").resolve())
    return repository["url"]


def repo_path(workspace_root: Path, repository: dict) -> Path:
    return (workspace_root / repository["path"]).resolve()


def _reason(code: str, detail: str, remediation: str) -> dict[str, str]:
    return {"code": code, "detail": detail, "remediation": remediation}


def guard_repository(repository: dict, path: Path, expected: str) -> dict:
    """Inspect a checkout without changing its worktree, refs, or configuration."""
    result = {
        "id": repository["id"],
        "path": str(path),
        "blocked": False,
        "reason_codes": [],
        "reasons": [],
        "state": "ready",
        "observed": {
            "ahead": None,
            "behind": None,
            "branch": None,
            "dirty": None,
            "head": None,
            "remote": None,
            "status_entries": [],
            "upstream": None,
        },
    }

    def add_reason(code: str, detail: str, remediation: str) -> None:
        result["reason_codes"].append(code)
        result["reasons"].append(_reason(code, detail, remediation))

    if not path.exists():
        add_reason(
            "missing",
            f"checkout does not exist at {path}",
            "run workspace init before assigning work",
        )
    elif not path.is_dir():
        add_reason(
            "invalid-checkout",
            f"checkout path {path} is not a directory",
            "preserve the path and resolve it manually",
        )
    else:
        code, _, error = run_git_optional(["rev-parse", "--is-inside-work-tree"], cwd=path)
        if code:
            add_reason(
                "invalid-checkout",
                error or f"{path} is not a Git worktree",
                "preserve the path and resolve it manually",
            )
        else:
            observed = result["observed"]
            remote_code, remote, remote_error = run_git_optional(["remote", "get-url", "origin"], cwd=path)
            if remote_code:
                add_reason(
                    "remote-mismatch",
                    remote_error or "origin remote is not configured",
                    f"configure origin as {expected!r} after human review",
                )
            else:
                observed["remote"] = remote
                if remote != expected:
                    add_reason(
                        "remote-mismatch",
                        f"expected origin {expected!r}, got {remote!r}",
                        "do not replace the checkout; resolve the remote manually",
                    )

            configured_id_code, configured_id, _ = run_git_optional(
                ["config", "--local", "--get", "orchestration.repo-id"], cwd=path
            )
            if configured_id_code == 0 and configured_id != repository["id"]:
                add_reason(
                    "repository-mismatch",
                    f"expected repository ID {repository['id']!r}, got {configured_id!r}",
                    "do not mutate the checkout; resolve repository identity manually",
                )

            status_entries = run_git(["status", "--porcelain", "--untracked-files=all"], cwd=path).splitlines()
            observed["status_entries"] = status_entries
            observed["dirty"] = bool(status_entries)
            if status_entries:
                add_reason(
                    "dirty",
                    f"working tree has {len(status_entries)} change(s)",
                    "commit, stash, or explicitly resolve the changes before orchestration",
                )
                untracked_count = sum(entry.startswith("?? ") for entry in status_entries)
                if untracked_count:
                    add_reason(
                        "untracked",
                        f"working tree has {untracked_count} untracked change(s)",
                        "preserve and resolve untracked files manually before orchestration",
                    )

            branch_code, branch, _ = run_git_optional(["symbolic-ref", "--short", "-q", "HEAD"], cwd=path)
            if branch_code:
                add_reason(
                    "detached",
                    "HEAD is detached and has no symbolic branch",
                    "restore the intended branch manually; do not checkout automatically",
                )
            else:
                observed["branch"] = branch

            head_code, head, head_error = run_git_optional(["rev-parse", "HEAD"], cwd=path)
            if head_code:
                add_reason(
                    "invalid-checkout",
                    head_error or "HEAD cannot be resolved",
                    "preserve the path and resolve the repository manually",
                )
            else:
                observed["head"] = head

            upstream_code, upstream, _ = run_git_optional(
                ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], cwd=path
            )
            if upstream_code:
                add_reason(
                    "upstream-missing",
                    "current branch has no upstream reference, so push state cannot be proven",
                    "configure and verify an upstream manually before orchestration",
                )
            else:
                observed["upstream"] = upstream
                counts_code, counts, counts_error = run_git_optional(
                    ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"], cwd=path
                )
                if counts_code:
                    add_reason(
                        "upstream-invalid",
                        counts_error or "upstream comparison failed",
                        "resolve the upstream reference manually",
                    )
                else:
                    ahead, behind = (int(value) for value in counts.split())
                    observed["ahead"] = ahead
                    observed["behind"] = behind
                    if ahead > 0 and behind > 0:
                        add_reason(
                            "diverged",
                            f"branch is ahead by {ahead} and behind by {behind}",
                            "resolve divergence manually; do not rebase, merge, or reset automatically",
                        )
                    elif ahead > 0:
                        add_reason(
                            "unpushed",
                            f"branch is ahead of upstream by {ahead} commit(s)",
                            "push or otherwise resolve local commits manually before orchestration",
                        )
                    elif behind > 0:
                        add_reason(
                            "behind",
                            f"branch is behind upstream by {behind} commit(s)",
                            "review and update the checkout manually before orchestration",
                        )

    result["blocked"] = bool(result["reasons"])
    result["state"] = "blocked" if result["blocked"] else "ready"
    return result


def format_guard_block(repository: dict, guard: dict) -> str:
    details = "; ".join(
        f"{reason['code']}: {reason['detail']} (remediation: {reason['remediation']})"
        for reason in guard["reasons"]
    )
    return f"{repository['id']} blocked: {details}"


def ensure_existing_checkout(path: Path, repository: dict, expected: str) -> str:
    guard = guard_repository(repository, path, expected)
    if guard["blocked"]:
        raise WorkspaceError(format_guard_block(repository, guard))
    return guard["observed"]["head"]


def clone_repository(repository: dict, destination: Path, remote: str) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix=".workspace-init-", dir=destination.parent))
    staging = staging_parent / repository["id"]
    try:
        run_git(["clone", "--branch", repository["default_branch"], remote, str(staging)])
        run_git(["config", "--local", "orchestration.repo-id", repository["id"]], cwd=staging)
        head = run_git(["rev-parse", "HEAD"], cwd=staging)
        os.replace(staging, destination)
        return head
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def workspace_relative(path: Path, workspace_root: Path) -> str:
    try:
        return str(path.relative_to(workspace_root.parent))
    except ValueError:
        return str(path)


def init_workspace(manifest: dict, workspace_root: Path, offline: bool, fixture_root: Path) -> dict:
    offline_remotes = None
    fixture_created = False
    if offline:
        offline_remotes, fixture_created = ensure_offline_remotes(manifest, fixture_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    records = []
    changed_count = 0
    for repository in manifest["repositories"]:
        destination = repo_path(workspace_root, repository)
        remote = expected_remote(repository, offline_remotes)
        if destination.exists():
            head = ensure_existing_checkout(destination, repository, remote)
            action = "unchanged"
            changed = False
        else:
            head = clone_repository(repository, destination, remote)
            action = "cloned"
            changed = True
        changed_count += int(changed)
        records.append(
            {
                "action": action,
                "changed": changed,
                "head": head,
                "id": repository["id"],
                "path": workspace_relative(destination, workspace_root),
                "remote": remote,
            }
        )
    return {
        "changed_count": changed_count,
        "command": "init",
        "fixture_created": fixture_created,
        "offline_fixture": offline,
        "repositories": records,
        "workspace_root": str(workspace_root),
    }


def fetch_workspace(manifest: dict, workspace_root: Path, offline: bool, fixture_root: Path) -> dict:
    offline_remotes = None
    fixture_created = False
    if offline:
        offline_remotes, fixture_created = ensure_offline_remotes(manifest, fixture_root)
    records = []
    changed_count = 0
    for repository in manifest["repositories"]:
        destination = repo_path(workspace_root, repository)
        if not destination.exists():
            raise WorkspaceError(
                f"{repository['id']} is not initialized at {destination}; "
                "remediation: run init first"
            )
        remote = expected_remote(repository, offline_remotes)
        ensure_existing_checkout(destination, repository, remote)
        before = run_git_optional(
            ["rev-parse", f"refs/remotes/origin/{repository['default_branch']}"], cwd=destination
        )[1]
        run_git(["fetch", "--prune", "origin"], cwd=destination)
        after = run_git_optional(
            ["rev-parse", f"refs/remotes/origin/{repository['default_branch']}"], cwd=destination
        )[1]
        changed = before != after
        changed_count += int(changed)
        records.append(
            {
                "action": "fetched",
                "changed": changed,
                "id": repository["id"],
                "path": workspace_relative(destination, workspace_root),
                "remote": remote,
            }
        )
    return {
        "changed_count": changed_count,
        "command": "fetch",
        "fixture_created": fixture_created,
        "offline_fixture": offline,
        "repositories": records,
        "workspace_root": str(workspace_root),
    }


def read_repo_status(repository: dict, workspace_root: Path) -> dict:
    destination = repo_path(workspace_root, repository)
    base = {
        "id": repository["id"],
        "path": workspace_relative(destination, workspace_root),
    }
    if not destination.exists():
        return {**base, "exists": False, "state": "missing"}
    code, _, error = run_git_optional(["rev-parse", "--is-inside-work-tree"], cwd=destination)
    if code:
        return {**base, "error": error or "not a Git worktree", "exists": True, "state": "invalid"}

    porcelain = run_git(["status", "--porcelain", "--untracked-files=all"], cwd=destination)
    branch_code, branch, _ = run_git_optional(["symbolic-ref", "--short", "-q", "HEAD"], cwd=destination)
    upstream_code, upstream, _ = run_git_optional(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], cwd=destination
    )
    ahead = behind = None
    if upstream_code == 0:
        counts = run_git(["rev-list", "--left-right", "--count", "HEAD...@{upstream}"], cwd=destination)
        ahead, behind = (int(value) for value in counts.split())
    return {
        **base,
        "ahead": ahead,
        "behind": behind,
        "branch": branch if branch_code == 0 else None,
        "dirty": bool(porcelain),
        "exists": True,
        "head": run_git(["rev-parse", "HEAD"], cwd=destination),
        "remote": run_git(["remote", "get-url", "origin"], cwd=destination),
        "state": "dirty" if porcelain else "clean",
        "status_entries": porcelain.splitlines(),
        "upstream": upstream if upstream_code == 0 else None,
    }


def status_workspace(manifest: dict, workspace_root: Path) -> dict:
    repositories = [read_repo_status(repository, workspace_root) for repository in manifest["repositories"]]
    return {
        "command": "status",
        "repositories": repositories,
        "workspace_root": str(workspace_root),
    }


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def commit_timestamp(path: Path) -> str | None:
    code, timestamp, _ = run_git_optional(["show", "-s", "--format=%cI", "HEAD"], cwd=path)
    return timestamp if code == 0 and timestamp else None


def deterministic_captured_at(timestamps: list[str]) -> str:
    parsed = []
    for timestamp in timestamps:
        try:
            parsed.append(datetime.fromisoformat(timestamp.replace("Z", "+00:00")))
        except ValueError:
            continue
    if not parsed:
        return "1970-01-01T00:00:00Z"
    latest = max(parsed).astimezone(timezone.utc).replace(microsecond=0)
    return latest.isoformat().replace("+00:00", "Z")


def normalize_snapshot_remote(remote: str | None, repository: dict, fixture_root: Path) -> str | None:
    if remote is None or remote == repository["url"]:
        return remote
    try:
        remote_path = Path(remote).resolve()
        expected_fixture = (fixture_remote_root(fixture_root) / f"{repository['id']}.git").resolve()
        if remote_path == expected_fixture:
            return f"offline://{repository['id']}"
    except OSError:
        pass
    return remote


def snapshot_repository(
    repository: dict, workspace_root: Path, fixture_root: Path
) -> tuple[dict, str | None]:
    status = read_repo_status(repository, workspace_root)
    destination = repo_path(workspace_root, repository)
    if "exchange_contracts" in repository:
        contract = {
            "direction": "exchange",
            "imports": list(repository["exchange_contracts"]["imports"]),
            "exports": list(repository["exchange_contracts"]["exports"]),
        }
    else:
        contract_field = "export_contract" if "export_contract" in repository else "import_contract"
        contract = {
            "direction": "export" if contract_field == "export_contract" else "import",
            "version": repository[contract_field],
        }
    quality_gates = list(repository["quality_gates"])
    quality_gate_hash = sha256_text(canonical_json(quality_gates))
    status_entries = status.get("status_entries", [])
    record = {
        "ahead": status.get("ahead"),
        "behind": status.get("behind"),
        "branch": status.get("branch"),
        "contract": contract,
        "default_branch": repository["default_branch"],
        "detached": status.get("branch") is None if status.get("exists") else None,
        "dirty": status.get("dirty"),
        "full_name": repository["full_name"],
        "head": status.get("head"),
        "id": repository["id"],
        "instructions": repository["instructions"],
        "manifest_observed_commit": repository["observed_commit"],
        "path": repository["path"],
        "quality_gate_hash": quality_gate_hash,
        "quality_gates": quality_gates,
        "remote": normalize_snapshot_remote(status.get("remote"), repository, fixture_root),
        "requirement_ssot": repository["requirement_ssot"],
        "state": status.get("state"),
        "status_entry_count": len(status_entries),
        "untracked": any(entry.startswith("?? ") for entry in status_entries),
        "upstream": status.get("upstream"),
    }
    return record, commit_timestamp(destination) if status.get("exists") else None


def build_snapshot(manifest: dict, workspace_root: Path, fixture_root: Path) -> tuple[dict, str]:
    repositories = []
    timestamps = []
    for repository in manifest["repositories"]:
        record, timestamp = snapshot_repository(repository, workspace_root, fixture_root)
        repositories.append(record)
        if timestamp:
            timestamps.append(timestamp)
    payload = {
        "captured_at": deterministic_captured_at(timestamps),
        "manifest_hash": sha256_text(canonical_json(manifest)),
        "manifest_version": manifest["version"],
        "repositories": repositories,
        "schema_version": 1,
        "workspace_root": manifest["workspace_root"],
    }
    payload["snapshot_hash"] = sha256_text(canonical_json(payload))
    markdown = render_snapshot_markdown(payload)
    return payload, markdown


def render_snapshot_markdown(snapshot: dict) -> str:
    lines = [
        "# Repository snapshot",
        "",
        f"- Snapshot hash: `{snapshot['snapshot_hash']}`",
        f"- Captured at: `{snapshot['captured_at']}`",
        f"- Manifest hash: `{snapshot['manifest_hash']}`",
        f"- Workspace root: `{snapshot['workspace_root']}`",
        "",
        "| ID | Role | Branch | HEAD | Upstream | Dirty | Untracked | Detached | Ahead | Behind | Contract | SSOT | Quality gate hash |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for repository in snapshot["repositories"]:
        direction = repository["contract"]["direction"]
        if direction == "exchange":
            imports = ",".join(repository["contract"]["imports"])
            exports = ",".join(repository["contract"]["exports"])
            contract = f"exchange:in={imports};out={exports}"
        else:
            contract = f"{direction}:{repository['contract']['version']}"
        lines.append(
            "| {id} | {role} | {branch} | `{head}` | {upstream} | {dirty} | {untracked} | {detached} | {ahead} | {behind} | {contract} | {ssot} | `{quality}` |".format(
                id=repository["id"],
                role=(
                    "consumer-runtime" if direction == "import"
                    else "control-plane-extension" if direction == "exchange"
                    else "input-kb"
                ),
                branch=repository["branch"] or "-",
                head=repository["head"] or "-",
                upstream=repository["upstream"] or "-",
                dirty=str(repository["dirty"]).lower(),
                untracked=str(repository["untracked"]).lower(),
                detached=str(repository["detached"]).lower(),
                ahead=repository["ahead"] if repository["ahead"] is not None else "-",
                behind=repository["behind"] if repository["behind"] is not None else "-",
                contract=contract,
                ssot=repository["requirement_ssot"],
                quality=repository["quality_gate_hash"],
            )
        )
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def snapshot_workspace(
    manifest: dict,
    workspace_root: Path,
    output_dir: Path,
    fixture_root: Path,
    check: bool,
) -> dict:
    snapshot, markdown = build_snapshot(manifest, workspace_root, fixture_root)
    json_path = output_dir / "snapshot.json"
    markdown_path = output_dir / "snapshot.md"
    json_content = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if check:
        second_snapshot, second_markdown = build_snapshot(manifest, workspace_root, fixture_root)
        if snapshot != second_snapshot or markdown != second_markdown:
            raise WorkspaceError("snapshot generation is not deterministic; remediation: remove time-dependent fields")
        json_exists = json_path.is_file()
        markdown_exists = markdown_path.is_file()
        if json_exists != markdown_exists:
            raise WorkspaceError(
                "snapshot output is incomplete; remediation: generate both snapshot.json and snapshot.md"
            )
        if json_exists:
            try:
                existing_json = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WorkspaceError(f"cannot read {json_path}: {exc}") from exc
            existing_markdown = markdown_path.read_text(encoding="utf-8")
            if existing_json != snapshot or existing_markdown != markdown:
                raise WorkspaceError(
                    "snapshot files are stale; remediation: run workspace.py snapshot to regenerate them"
                )
        return {
            "changed": False,
            "command": "snapshot",
            "files_present": json_exists,
            "json": str(json_path),
            "markdown": str(markdown_path),
            "snapshot_hash": snapshot["snapshot_hash"],
        }

    json_changed = write_atomic(json_path, json_content)
    markdown_changed = write_atomic(markdown_path, markdown)
    return {
        "changed": json_changed or markdown_changed,
        "command": "snapshot",
        "files_present": True,
        "json": str(json_path),
        "markdown": str(markdown_path),
        "snapshot_hash": snapshot["snapshot_hash"],
    }


def guard_workspace(manifest: dict, workspace_root: Path, offline: bool, fixture_root: Path) -> dict:
    """Return blocking state without creating fixtures or touching any checkout."""
    offline_remotes = fixture_remote_root(fixture_root) if offline else None
    repositories = []
    for repository in manifest["repositories"]:
        destination = repo_path(workspace_root, repository)
        expected = expected_remote(repository, offline_remotes)
        repositories.append(guard_repository(repository, destination, expected))
    return {
        "blocked_count": sum(int(repository["blocked"]) for repository in repositories),
        "command": "guard",
        "offline_fixture": offline,
        "repositories": repositories,
        "workspace_root": str(workspace_root),
    }


def _absolute_lexical_path(path: Path) -> Path:
    """Make a path absolute without resolving symlink components."""
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def bootstrap_lock_path(workspace_root: Path) -> Path:
    """Return the tool-owned lock path without reading or creating it."""
    return _absolute_lexical_path(workspace_root) / BOOTSTRAP_LOCK_NAME


def acquire_bootstrap_lock(workspace_root: Path, manifest: dict) -> bool:
    """Acquire an exclusive, metadata-only lock for a future bootstrap apply."""
    workspace_root = _absolute_lexical_path(workspace_root)
    if workspace_root.is_symlink():
        raise WorkspaceError(
            "workspace root is a symlink; remediation: use a dedicated real directory for bootstrap"
        )
    workspace_root.mkdir(parents=True, exist_ok=True)
    lock_path = bootstrap_lock_path(workspace_root)
    payload = {
        "contract_version": "workspace-bootstrap-lock/v1",
        "manifest_hash": sha256_text(canonical_json(manifest)),
        "owner": "agentic-art-orchestration",
        "acquired_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(payload) + "\n")
    except Exception:
        lock_path.unlink(missing_ok=True)
        raise
    return True


def release_bootstrap_lock(workspace_root: Path) -> None:
    """Release only the lock acquired by this process; never remove a stale lock."""
    workspace_root = _absolute_lexical_path(workspace_root)
    if workspace_root.is_symlink():
        return
    bootstrap_lock_path(workspace_root).unlink(missing_ok=True)


def _bootstrap_reason_codes(reason_codes: list[str] | tuple[str, ...]) -> list[str]:
    mapped = {BOOTSTRAP_FINDING_CODES.get(code, code.upper().replace("-", "_")) for code in reason_codes}
    return [code for code in BOOTSTRAP_FINDING_ORDER if code in mapped] + sorted(
        mapped.difference(BOOTSTRAP_FINDING_ORDER)
    )


def _bootstrap_record(
    repository: dict,
    *,
    action: str,
    head: str | None,
    guard_status: str,
    reason_codes: list[str] | tuple[str, ...] = (),
) -> dict:
    """Build one closed, sanitized bootstrap repository record."""
    safe_head = head if isinstance(head, str) and len(head) == 40 and all(character in "0123456789abcdef" for character in head) else None
    codes = _bootstrap_reason_codes(list(reason_codes))
    if safe_head is None:
        pin_status = "NOT_RUN"
    elif safe_head == repository["observed_commit"]:
        pin_status = "MATCHED"
    else:
        pin_status = "DRIFTED"
        if "PIN_DRIFT" not in codes:
            codes.append("PIN_DRIFT")
            codes = _bootstrap_reason_codes(codes)
    if not codes and action == "not-run":
        codes = ["NOT_RUN"]
    return {
        "id": repository["id"],
        "full_name": repository["full_name"],
        "path": repository["path"],
        "action": action,
        "head": safe_head,
        "observed_commit": repository["observed_commit"],
        "pin_status": pin_status,
        "guard_status": guard_status,
        "finding_codes": codes,
    }


def _workspace_destination_issues(manifest: dict, workspace_root: Path) -> dict[str, list[str]]:
    """Find unsafe root, symlink, and overlapping destinations before Git reads."""
    issues: dict[str, list[str]] = {repository["id"]: [] for repository in manifest["repositories"]}
    lexical_root = _absolute_lexical_path(workspace_root)
    root = lexical_root.resolve(strict=False)
    if lexical_root.is_symlink() or root == ROOT or ROOT.is_relative_to(root):
        for repository in manifest["repositories"]:
            issues[repository["id"]].append("invalid-checkout")
        return issues
    if root.exists() and not root.is_dir():
        for repository in manifest["repositories"]:
            issues[repository["id"]].append("non-directory")
        return issues

    destinations: list[tuple[str, Path]] = []
    for repository in manifest["repositories"]:
        repository_id = repository["id"]
        lexical = lexical_root / repository["path"]
        destination = lexical.resolve(strict=False)
        try:
            destination.relative_to(root)
        except ValueError:
            issues[repository_id].append("invalid-checkout")
            continue
        current = root
        symlinked = False
        for part in Path(repository["path"]).parts:
            current = current / part
            if current.is_symlink():
                symlinked = True
                break
        if symlinked:
            issues[repository_id].append("invalid-checkout")
            continue
        destinations.append((repository_id, destination))

    for index, (repository_id, destination) in enumerate(destinations):
        for other_id, other in destinations[index + 1:]:
            if destination == other or destination in other.parents or other in destination.parents:
                issues[repository_id].append("invalid-checkout")
                issues[other_id].append("invalid-checkout")
    return issues


def _remote_access_preflight(remote: str) -> bool:
    """Probe remote read access without allowing prompts or retaining output."""
    environment = os.environ.copy()
    environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "--quiet", remote],
            cwd=None,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _bootstrap_preflight_remediation(status: str) -> list[str]:
    remediations = {
        "BLOCKED_EXISTING_WORKSPACE": [
            "preserve existing checkout changes and resolve the reported workspace guard findings manually",
            "rerun bootstrap after every manifest destination is a clean, non-detached, pin-reviewable checkout",
        ],
        "BLOCKED_REMOTE_ACCESS": [
            "resolve Git remote access or credential configuration manually without placing credentials in the report",
            "rerun bootstrap with the same manifest and workspace after every missing remote is readable",
        ],
        "BLOCKED_PIN_DRIFT": [
            "review pin drift with startup and pin_adopt --dry-run; do not auto-checkout or update the manifest",
            "rerun bootstrap after the qualified pin decision is completed through its human-gated workflow",
        ],
        "BLOCKED_RACE": [
            "inspect the existing bootstrap lock owner and staging state manually; do not delete the lock automatically",
            "rerun bootstrap after the concurrent bootstrap has completed or the operator has recovered it",
        ],
        "FAILED": [
            "read-only preflight passed for the available entries; the staged bootstrap apply task must place missing checkouts",
            "use a fresh temporary workspace or wait for the bootstrap apply implementation before assigning child work",
        ],
    }
    return remediations.get(status, ["inspect the sanitized bootstrap findings and resolve the precondition manually"])


def validate_bootstrap_result(result: dict, source: str = "workspace-bootstrap") -> list[str]:
    """Validate the closed result and the status/exit-code relationship."""
    errors = _schema_errors(result, load_json(WORKSPACE_BOOTSTRAP_SCHEMA), source)
    if errors or not isinstance(result, dict):
        return errors
    status = result.get("status")
    expected_exit = BOOTSTRAP_STATUS_EXIT_CODES.get(status)
    if result.get("exit_code") != expected_exit:
        errors.append(
            f"{source}.exit_code: {status} must use exit {expected_exit}; "
            "remediation: preserve the fixed bootstrap status vocabulary"
        )
    repositories = result.get("repositories", [])
    ids = [item.get("id") for item in repositories if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        errors.append(f"{source}.repositories: repository IDs must be unique; remediation: emit one record per manifest entry")
    if result.get("changed_count") != sum(item.get("action") == "cloned" for item in repositories if isinstance(item, dict)):
        errors.append(
            f"{source}.changed_count: must equal cloned repository count; "
            "remediation: count only newly placed checkouts"
        )
    if status == "READY":
        for item in repositories:
            if not isinstance(item, dict):
                continue
            if item.get("action") not in {"cloned", "reused"}:
                errors.append(f"{source}.repositories[{item.get('id')}]: READY cannot contain not-run; remediation: complete every manifest entry")
            if item.get("pin_status") != "MATCHED" or item.get("guard_status") != "PASS":
                errors.append(f"{source}.repositories[{item.get('id')}]: READY requires matched pin and passing guard; remediation: preserve fail-closed readiness")
            if item.get("finding_codes"):
                errors.append(f"{source}.repositories[{item.get('id')}]: READY cannot hide findings; remediation: return a blocking status")
    elif not result.get("remediations"):
        errors.append(f"{source}.remediations: non-ready result needs remediation; remediation: state the next safe human action")
    return errors


def build_bootstrap_result(
    manifest: dict,
    workspace_root: Path,
    *,
    status: str,
    repositories: list[dict],
    changed_count: int,
    offline_fixture: bool,
    remediations: list[str] | tuple[str, ...] = (),
    lock_status: str = "RELEASED",
) -> dict:
    """Build canonical bootstrap evidence in manifest order without hardcoding IDs."""
    if status not in BOOTSTRAP_STATUS_EXIT_CODES:
        raise WorkspaceError(f"unknown bootstrap status {status!r}; remediation: use workspace-bootstrap/v1")
    if not isinstance(repositories, list):
        raise WorkspaceError("bootstrap repositories must be a list; remediation: emit one record per manifest entry")
    by_id: dict[str, dict] = {}
    for record in repositories:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise WorkspaceError("bootstrap repository record is malformed; remediation: include the manifest repository ID")
        repository_id = record["id"]
        if repository_id in by_id:
            raise WorkspaceError(f"bootstrap repository {repository_id!r} is duplicated; remediation: emit one record per manifest entry")
        by_id[repository_id] = dict(record)
    manifest_ids = [repository.get("id") for repository in manifest.get("repositories", [])]
    if set(by_id) != set(manifest_ids):
        raise WorkspaceError("bootstrap records do not match the manifest repository set; remediation: derive records from repositories.yaml")
    ordered = [by_id[repository_id] for repository_id in manifest_ids]
    if not isinstance(changed_count, int) or isinstance(changed_count, bool) or changed_count < 0:
        raise WorkspaceError("bootstrap changed_count is invalid; remediation: count newly cloned entries")
    if any(not isinstance(item, str) or not item for item in remediations):
        raise WorkspaceError("bootstrap remediation is invalid; remediation: use sanitized non-empty instructions")
    result = {
        "contract_version": "workspace-bootstrap/v1",
        "command": "bootstrap",
        "status": status,
        "exit_code": BOOTSTRAP_STATUS_EXIT_CODES[status],
        "manifest_hash": sha256_text(canonical_json(manifest)),
        "workspace_root": str(workspace_root.expanduser().resolve()),
        "offline_fixture": bool(offline_fixture),
        "changed_count": changed_count,
        "repositories": ordered,
        "remediations": sorted(set(remediations)),
        "lock_status": lock_status,
        "remote_operations": [],
        "child_mutations": [],
        "privacy": {
            "credentials_stored": False,
            "token_stored": False,
            "remote_response_stored": False,
        },
    }
    errors = validate_bootstrap_result(result)
    if errors:
        raise WorkspaceError("bootstrap result is invalid:\n" + "\n".join(f"- {error}" for error in errors))
    return result


def bootstrap_workspace(manifest: dict, workspace_root: Path, offline: bool, fixture_root: Path) -> dict:
    """Preflight every destination and missing remote before a future apply stage."""
    workspace_root = _absolute_lexical_path(workspace_root)
    destination_issues = _workspace_destination_issues(manifest, workspace_root)
    resolved_root = workspace_root.resolve(strict=False)
    root_is_unsafe = (
        workspace_root.is_symlink()
        or resolved_root == ROOT
        or ROOT.is_relative_to(resolved_root)
        or (workspace_root.exists() and not workspace_root.is_dir())
    )
    if any(destination_issues.values()) and root_is_unsafe:
        records = [
            _bootstrap_record(
                repository,
                action="not-run",
                head=None,
                guard_status="NOT_RUN",
                reason_codes=destination_issues[repository["id"]] or ["invalid-checkout"],
            )
            for repository in manifest["repositories"]
        ]
        return build_bootstrap_result(
            manifest,
            workspace_root,
            status="FAILED",
            repositories=records,
            changed_count=0,
            offline_fixture=offline,
            remediations=[
                "use a dedicated external workspace directory that is not the orchestration repository or its ancestor",
                "preserve the unsafe path and resolve it manually before bootstrap",
            ],
            lock_status="NOT_ACQUIRED",
        )

    if workspace_root.exists() and bootstrap_lock_path(workspace_root).exists():
        records = [
            _bootstrap_record(
                repository,
                action="not-run",
                head=None,
                guard_status="NOT_RUN",
                reason_codes=["race"],
            )
            for repository in manifest["repositories"]
        ]
        return build_bootstrap_result(
            manifest,
            workspace_root,
            status="BLOCKED_RACE",
            repositories=records,
            changed_count=0,
            offline_fixture=offline,
            remediations=_bootstrap_preflight_remediation("BLOCKED_RACE"),
            lock_status="BLOCKED_EXISTING",
        )

    offline_remotes = None
    if offline:
        offline_remotes, _ = ensure_offline_remotes(manifest, fixture_root)

    records_by_id: dict[str, dict] = {}
    existing_blocked = False
    missing: list[tuple[dict, str]] = []
    pin_drift = False
    for repository in manifest["repositories"]:
        repository_id = repository["id"]
        issues = destination_issues[repository_id]
        destination = repo_path(workspace_root, repository)
        if issues:
            records_by_id[repository_id] = _bootstrap_record(
                repository,
                action="not-run",
                head=None,
                guard_status="BLOCKED",
                reason_codes=issues,
            )
            existing_blocked = True
            continue
        if not destination.exists():
            missing.append((repository, expected_remote(repository, offline_remotes)))
            records_by_id[repository_id] = _bootstrap_record(
                repository,
                action="not-run",
                head=None,
                guard_status="NOT_RUN",
                reason_codes=["not-run"],
            )
            continue
        try:
            guard = guard_repository(repository, destination, expected_remote(repository, offline_remotes))
        except (OSError, WorkspaceError):
            guard = {"blocked": True, "reason_codes": ["invalid-checkout"], "observed": {"head": None}}
        record = _bootstrap_record(
            repository,
            action="reused" if not guard.get("blocked") else "not-run",
            head=guard.get("observed", {}).get("head") if isinstance(guard.get("observed"), dict) else None,
            guard_status="PASS" if not guard.get("blocked") else "BLOCKED",
            reason_codes=guard.get("reason_codes", []),
        )
        records_by_id[repository_id] = record
        if record["guard_status"] != "PASS":
            existing_blocked = True
        if "PIN_DRIFT" in record["finding_codes"]:
            pin_drift = True

    if existing_blocked:
        records = [records_by_id[repository["id"]] for repository in manifest["repositories"]]
        return build_bootstrap_result(
            manifest,
            workspace_root,
            status="BLOCKED_EXISTING_WORKSPACE",
            repositories=records,
            changed_count=0,
            offline_fixture=offline,
            remediations=_bootstrap_preflight_remediation("BLOCKED_EXISTING_WORKSPACE"),
            lock_status="NOT_ACQUIRED",
        )

    remote_blocked = False
    for repository, remote in missing:
        if not _remote_access_preflight(remote):
            remote_blocked = True
            record = records_by_id[repository["id"]]
            record["finding_codes"] = _bootstrap_reason_codes(["remote-access"])
    if remote_blocked:
        records = [records_by_id[repository["id"]] for repository in manifest["repositories"]]
        return build_bootstrap_result(
            manifest,
            workspace_root,
            status="BLOCKED_REMOTE_ACCESS",
            repositories=records,
            changed_count=0,
            offline_fixture=offline,
            remediations=_bootstrap_preflight_remediation("BLOCKED_REMOTE_ACCESS"),
            lock_status="NOT_ACQUIRED",
        )

    if pin_drift:
        records = [records_by_id[repository["id"]] for repository in manifest["repositories"]]
        return build_bootstrap_result(
            manifest,
            workspace_root,
            status="BLOCKED_PIN_DRIFT",
            repositories=records,
            changed_count=0,
            offline_fixture=offline,
            remediations=_bootstrap_preflight_remediation("BLOCKED_PIN_DRIFT"),
            lock_status="NOT_ACQUIRED",
        )

    if missing:
        if not acquire_bootstrap_lock(workspace_root, manifest):
            for repository, _ in missing:
                record = records_by_id[repository["id"]]
                record["finding_codes"] = _bootstrap_reason_codes(["race"])
            records = [records_by_id[repository["id"]] for repository in manifest["repositories"]]
            return build_bootstrap_result(
                manifest,
                workspace_root,
                status="BLOCKED_RACE",
                repositories=records,
                changed_count=0,
                offline_fixture=offline,
                remediations=_bootstrap_preflight_remediation("BLOCKED_RACE"),
                lock_status="BLOCKED_EXISTING",
            )
        try:
            lock_status = "RELEASED"
        finally:
            release_bootstrap_lock(workspace_root)
        records = [records_by_id[repository["id"]] for repository in manifest["repositories"]]
        return build_bootstrap_result(
            manifest,
            workspace_root,
            status="FAILED",
            repositories=records,
            changed_count=0,
            offline_fixture=offline,
            remediations=_bootstrap_preflight_remediation("FAILED"),
            lock_status=lock_status,
        )

    records = [records_by_id[repository["id"]] for repository in manifest["repositories"]]
    return build_bootstrap_result(
        manifest,
        workspace_root,
        status="READY",
        repositories=records,
        changed_count=0,
        offline_fixture=offline,
        remediations=[],
        lock_status="RELEASED",
    )


def print_result(result: dict, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if result.get("command") == "bootstrap":
        print(f"workspace: {result['workspace_root']}")
        print(f"status: {result['status']} (exit {result['exit_code']})")
        for repository in result["repositories"]:
            findings = ",".join(repository["finding_codes"]) or "none"
            print(f"{repository['id']}: {repository['action']} / pin={repository['pin_status']} / findings={findings}")
        for remediation in result["remediations"]:
            print(f"remediation: {remediation}")
        return
    print(f"workspace: {result['workspace_root']}")
    for repository in result["repositories"]:
        print(f"{repository['id']}: {repository.get('state', repository.get('action'))}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage manifest-declared repository checkouts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "fetch"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--offline-fixture", action="store_true")
        command_parser.add_argument("--fixture-root", type=Path, default=DEFAULT_OFFLINE_FIXTURE_ROOT)
        command_parser.add_argument("--workspace-root", type=Path)
    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--offline-fixture", action="store_true")
    bootstrap_parser.add_argument("--fixture-root", type=Path, default=DEFAULT_OFFLINE_FIXTURE_ROOT)
    bootstrap_parser.add_argument("--json", action="store_true")
    bootstrap_parser.add_argument("--workspace-root", type=Path)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--json", action="store_true")
    status_parser.add_argument("--workspace-root", type=Path)
    guard_parser = subparsers.add_parser("guard")
    guard_parser.add_argument("--offline-fixture", action="store_true")
    guard_parser.add_argument("--fixture-root", type=Path, default=DEFAULT_OFFLINE_FIXTURE_ROOT)
    guard_parser.add_argument("--json", action="store_true")
    guard_parser.add_argument("--workspace-root", type=Path)
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--check", action="store_true")
    snapshot_parser.add_argument("--fixture-root", type=Path, default=DEFAULT_OFFLINE_FIXTURE_ROOT)
    snapshot_parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    snapshot_parser.add_argument("--workspace-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = load_manifest()
        workspace_root = resolve_workspace_root(manifest, args.workspace_root)
        fixture_root = resolve_path(args.fixture_root) if hasattr(args, "fixture_root") else DEFAULT_OFFLINE_FIXTURE_ROOT
        if args.command == "bootstrap":
            result = bootstrap_workspace(manifest, workspace_root, args.offline_fixture, fixture_root)
            print_result(result, as_json=args.json)
            return result["exit_code"]
        if args.command == "init":
            result = init_workspace(manifest, workspace_root, args.offline_fixture, fixture_root)
            print_result(result)
        elif args.command == "fetch":
            result = fetch_workspace(manifest, workspace_root, args.offline_fixture, fixture_root)
            print_result(result)
        elif args.command == "status":
            result = status_workspace(manifest, workspace_root)
            print_result(result, as_json=args.json)
        else:
            if args.command == "guard":
                result = guard_workspace(manifest, workspace_root, args.offline_fixture, fixture_root)
                print_result(result, as_json=args.json)
                return 2 if result["blocked_count"] else 0
            result = snapshot_workspace(
                manifest,
                workspace_root,
                resolve_path(args.output_dir),
                resolve_path(args.fixture_root),
                args.check,
            )
            print_result(result)
        return 0
    except (OSError, ValueError, WorkspaceError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
