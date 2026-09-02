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

from validate import load_yaml, validate_manifest  # noqa: E402


DEFAULT_MANIFEST = ROOT / "config/repositories.yaml"
DEFAULT_OFFLINE_FIXTURE_ROOT = Path(tempfile.gettempdir()) / "agentic-art-orchestration-offline-fixture"


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


def run_git_optional(args: list[str], cwd: Path) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
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


def print_result(result: dict, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
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
