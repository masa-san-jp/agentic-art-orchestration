#!/usr/bin/env python3
"""Render deterministic portfolio status from workspace and orchestration state."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]

try:
    from tools.validate import load_yaml
    from tools.workspace import load_manifest, read_repo_status, resolve_workspace_root
except ModuleNotFoundError:  # pragma: no cover - exercised by direct CLI use
    sys.path.insert(0, str(ROOT))
    from tools.validate import load_yaml
    from tools.workspace import load_manifest, read_repo_status, resolve_workspace_root


class StatusError(ValueError):
    """Status inputs or generated output are invalid."""


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _error(detail: str, remediation: str) -> StatusError:
    return StatusError(f"status: {detail}; remediation: {remediation}")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise _error("timestamp must be a string", "record an ISO-8601 timestamp in source state")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error(f"invalid timestamp {value!r}", "use an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise _error("timestamp must include timezone", "include Z or an explicit UTC offset")
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _max_timestamp(*values: object) -> str:
    parsed = [_parse_timestamp(value) for value in values if value is not None]
    if not parsed:
        return "1970-01-01T00:00:00Z"
    return max(parsed).isoformat().replace("+00:00", "Z")


def _repo_view(repository: Mapping[str, object]) -> dict:
    fields = (
        "id",
        "branch",
        "head",
        "upstream",
        "dirty",
        "untracked",
        "detached",
        "ahead",
        "behind",
        "state",
    )
    return {field: repository.get(field) for field in fields if field in repository}


def _live_field(repository: Mapping[str, object], field: str) -> object:
    if field == "untracked":
        return any(str(entry).startswith("?? ") for entry in repository.get("status_entries", []))
    if field == "detached":
        return bool(repository.get("exists")) and repository.get("branch") is None
    return repository.get(field)


def _drift(
    snapshot_repositories: list[dict],
    live_repositories: list[dict],
    snapshot_manifest_hash: str | None,
    manifest_hash: str | None,
) -> list[dict]:
    live_by_id = {repo.get("id"): repo for repo in live_repositories}
    drift: list[dict] = []
    for expected in sorted(snapshot_repositories, key=lambda repo: str(repo.get("id"))):
        repository_id = expected.get("id")
        actual = live_by_id.get(repository_id)
        if actual is None:
            drift.append({"repository": repository_id, "reason": "repository missing from live status"})
            continue
        differences = {}
        for field in ("branch", "head", "upstream", "dirty", "untracked", "detached", "ahead", "behind"):
            live_value = _live_field(actual, field)
            if expected.get(field) != live_value:
                differences[field] = {"snapshot": expected.get(field), "live": live_value}
        if differences:
            drift.append({"repository": repository_id, "differences": differences})
    snapshot_ids = {repo.get("id") for repo in snapshot_repositories}
    for actual in sorted(live_repositories, key=lambda repo: str(repo.get("id"))):
        if actual.get("id") not in snapshot_ids:
            drift.append({"repository": actual.get("id"), "reason": "live repository is absent from snapshot"})
    if snapshot_manifest_hash and manifest_hash is not None and snapshot_manifest_hash != manifest_hash:
        drift.append(
            {
                "repository": "workspace",
                "reason": "snapshot manifest hash differs from current manifest",
                "snapshot": snapshot_manifest_hash,
                "live": manifest_hash,
            }
        )
    return drift


def _next_work(tasks: list[dict]) -> dict:
    by_id = {task.get("id"): task for task in tasks if isinstance(task, dict)}
    ready: list[dict] = []
    for task_id in sorted(by_id, key=lambda value: str(value)):
        task = by_id[task_id]
        if task.get("status") != "READY":
            continue
        dependencies = task.get("depends_on", [])
        if all(by_id.get(dependency, {}).get("status") == "DONE" for dependency in dependencies):
            ready.append(task)
    if not ready:
        return {"task": None, "status": "NONE", "reason": "no READY task has all dependencies DONE"}
    selected = ready[0]
    return {
        "task": selected.get("id"),
        "status": "READY",
        "reason": "lowest-ID READY task with all dependencies DONE",
        "depends_on": list(selected.get("depends_on", [])),
    }


def _compatibility(repositories: list[dict]) -> dict:
    exports = []
    imports = []
    for repository in repositories:
        contract = repository.get("contract", {})
        record = {
            "repository": repository.get("id"),
            "version": contract.get("version"),
            "direction": contract.get("direction"),
            "source_commit": repository.get("head"),
        }
        if contract.get("direction") == "export":
            exports.append(record)
        elif contract.get("direction") == "import":
            imports.append(record)
    versions = {entry.get("version") for entry in exports + imports}
    compatible = bool(exports) and len(imports) == 1 and versions == {"normalized-research-signal/v1"}
    return {
        "status": "COMPATIBLE" if compatible else "INCOMPATIBLE",
        "contract": "normalized-research-signal/v1",
        "exporters": sorted(exports, key=lambda entry: str(entry.get("repository"))),
        "consumers": sorted(imports, key=lambda entry: str(entry.get("repository"))),
    }


def build_status(
    snapshot: dict,
    queue: dict,
    state: dict,
    live_repositories: list[dict],
    manifest_hash: str | None = None,
) -> dict:
    """Build a JSON-serializable portfolio view without mutating any input."""
    if not isinstance(snapshot, dict) or not isinstance(queue, dict) or not isinstance(state, dict):
        raise _error("snapshot, queue, and state must be objects", "load the three repository SSOT files")
    snapshot_repositories = snapshot.get("repositories")
    if not isinstance(snapshot_repositories, list):
        raise _error("snapshot.repositories must be a list", "regenerate the repository snapshot")
    if not isinstance(live_repositories, list):
        raise _error("live_repositories must be a list", "read workspace status before rendering")
    tasks = queue.get("tasks")
    if not isinstance(tasks, list):
        raise _error("queue.tasks must be a list", "repair execution/task-queue.yaml")

    snapshot_hash = snapshot.get("snapshot_hash")
    live_by_id = {repo.get("id"): repo for repo in live_repositories}
    commits = []
    child_progress = []
    for expected in sorted(snapshot_repositories, key=lambda repo: str(repo.get("id"))):
        repository_id = expected.get("id")
        live = live_by_id.get(repository_id, {})
        commits.append(
            {
                "repository": repository_id,
                "source_commit": live.get("head", expected.get("head")),
                "manifest_observed_commit": expected.get("manifest_observed_commit"),
                "branch": live.get("branch", expected.get("branch")),
            }
        )
        child_progress.append(
            {
                "repository": repository_id,
                "source_commit": live.get("head", expected.get("head")),
                "state": live.get("state", "missing"),
                "dirty": live.get("dirty"),
                "ahead": live.get("ahead"),
                "behind": live.get("behind"),
                "detached": _live_field(live, "detached"),
                "quality_gate_hash": expected.get("quality_gate_hash"),
            }
        )

    drift = _drift(snapshot_repositories, live_repositories, snapshot.get("manifest_hash"), manifest_hash)
    compatibility = _compatibility(snapshot_repositories)
    blockers: list[dict] = []
    for task in sorted(tasks, key=lambda item: str(item.get("id")) if isinstance(item, dict) else ""):
        if isinstance(task, dict) and task.get("status") == "BLOCKED":
            blockers.append({"type": "task", "id": task.get("id"), "detail": "task is BLOCKED"})
    for entry in state.get("blocked", []) if isinstance(state.get("blocked", []), list) else []:
        blockers.append({"type": "runtime", "detail": entry})
    if drift:
        blockers.append({"type": "drift", "detail": "workspace differs from deterministic snapshot"})
    if compatibility["status"] != "COMPATIBLE":
        blockers.append({"type": "compatibility", "detail": "export/import contract set is incompatible"})
    for child in child_progress:
        if child["dirty"] or child["detached"] or (child["ahead"] not in (None, 0)) or (child["behind"] not in (None, 0)):
            blockers.append(
                {
                    "type": "repository",
                    "repository": child["repository"],
                    "source_commit": child["source_commit"],
                    "detail": "Git state guard requires review",
                }
            )

    generated_at = _max_timestamp(snapshot.get("captured_at"), queue.get("updated_at"), state.get("updated_at"))
    result = {
        "version": 1,
        "generated_at": generated_at,
        "snapshot": {"captured_at": snapshot.get("captured_at"), "snapshot_hash": snapshot_hash},
        "commits": commits,
        "drift": {"status": "DRIFT" if drift else "CLEAN", "items": drift},
        "child_progress": child_progress,
        "compatibility": compatibility,
        "blockers": blockers,
        "next_work": _next_work(tasks),
        "active_task": state.get("active_task"),
    }
    return result


def render_markdown(status: dict) -> str:
    lines = [
        "# Portfolio status",
        "",
        f"- Generated at: `{status['generated_at']}`",
        f"- Snapshot: `{status['snapshot']['snapshot_hash']}`",
        f"- Drift: **{status['drift']['status']}**",
        f"- Compatibility: **{status['compatibility']['status']}**",
        "",
        "## Commits",
        "",
        "| Repository | Source commit | Manifest observed commit | Branch |",
        "| --- | --- | --- | --- |",
    ]
    for commit in status["commits"]:
        lines.append(
            f"| {commit['repository']} | `{commit['source_commit']}` | `{commit['manifest_observed_commit']}` | {commit['branch']} |"
        )
    lines.extend([
        "",
        "## Child progress",
        "",
        "| Repository | State | Dirty | Ahead | Behind | Detached | Source commit |",
        "| --- | --- | --- | ---: | ---: | --- | --- |",
    ])
    for child in status["child_progress"]:
        lines.append(
            f"| {child['repository']} | {child['state']} | {str(child['dirty']).lower()} | {child['ahead']} | {child['behind']} | {str(child['detached']).lower()} | `{child['source_commit']}` |"
        )
    lines.extend(["", "## Drift", ""])
    if status["drift"]["items"]:
        for item in status["drift"]["items"]:
            lines.append(f"- `{item['repository']}`: {item.get('reason', 'field differences detected')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Blockers", ""])
    if status["blockers"]:
        for blocker in status["blockers"]:
            subject = blocker.get("repository", blocker.get("id", blocker.get("type", "runtime")))
            lines.append(f"- `{subject}`: {blocker['detail']}")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Next work",
        "",
        f"- Task: `{status['next_work']['task']}`",
        f"- Status: {status['next_work']['status']}",
        f"- Reason: {status['next_work']['reason']}",
        "",
    ])
    return "\n".join(lines)


def _write_atomic(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8")
        changed = not path.exists() or path.read_text(encoding="utf-8") != content
        os.replace(temporary, path)
        return changed
    finally:
        temporary.unlink(missing_ok=True)


def load_inputs(output_dir: Path, workspace_root: Path) -> tuple[dict, dict, dict, list[dict], str]:
    snapshot_path = output_dir / "snapshot.json"
    if not snapshot_path.is_file():
        raise _error("snapshot.json is missing", "run workspace.py snapshot before status")
    with snapshot_path.open(encoding="utf-8") as handle:
        snapshot = json.load(handle)
    queue = load_yaml(ROOT / "execution/task-queue.yaml")
    state = load_yaml(ROOT / "execution/state.yaml")
    manifest = load_manifest()
    live = [read_repo_status(repository, workspace_root) for repository in manifest["repositories"]]
    return snapshot, queue, state, live, sha256_text(canonical_json(manifest))


def run_status(output_dir: Path, workspace_root: Path, check: bool) -> dict:
    snapshot, queue, state, live, manifest_hash = load_inputs(output_dir, workspace_root)
    status = build_status(snapshot, queue, state, live, manifest_hash)
    markdown = render_markdown(status)
    json_content = json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    json_path = output_dir / "status.json"
    markdown_path = output_dir / "status.md"
    if check:
        second_snapshot, second_queue, second_state, second_live, second_manifest_hash = load_inputs(output_dir, workspace_root)
        second_status = build_status(second_snapshot, second_queue, second_state, second_live, second_manifest_hash)
        second_markdown = render_markdown(second_status)
        if status != second_status or markdown != second_markdown:
            raise _error("status generation is not deterministic", "remove time-dependent or unordered fields")
        if not json_path.is_file() or not markdown_path.is_file():
            raise _error("status output is missing", "run status without --check to materialize JSON and Markdown")
        if json_path.read_text(encoding="utf-8") != json_content or markdown_path.read_text(encoding="utf-8") != markdown:
            raise _error("status output is stale", "rerun status without --check to regenerate both files")
        return {"command": "status", "changed": False, "json": str(json_path), "markdown": str(markdown_path), "next_task": status["next_work"]["task"]}
    json_changed = _write_atomic(json_path, json_content)
    markdown_changed = _write_atomic(markdown_path, markdown)
    return {
        "command": "status",
        "changed": json_changed or markdown_changed,
        "json": str(json_path),
        "markdown": str(markdown_path),
        "next_task": status["next_work"]["task"],
        "drift": status["drift"]["status"],
        "blocker_count": len(status["blockers"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render portfolio status and drift report")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--offline-fixture", action="store_true", help="use the local synthetic workspace checkout")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--workspace-root", type=Path, default=None)
    args = parser.parse_args()
    try:
        manifest = load_manifest()
        workspace_root = resolve_workspace_root(manifest, str(args.workspace_root) if args.workspace_root else None)
        result = run_status(args.output_dir.resolve(), workspace_root, args.check)
    except (OSError, StatusError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
