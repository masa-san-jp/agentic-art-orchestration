#!/usr/bin/env python3
"""Build a deterministic, metadata-only report for open pull requests.

The command observes GitHub PR metadata through ``gh`` or a checked-in fixture.
It never merges, rebases, closes, labels, comments on, or otherwise mutates a
repository or pull request.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

try:
    from tools.validate import _schema_errors, load_json, load_yaml
except ModuleNotFoundError:  # pragma: no cover - direct CLI execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.validate import _schema_errors, load_json, load_yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config/repositories.yaml"
QUEUE_PATH = ROOT / "execution/task-queue.yaml"
SCHEMA_PATH = ROOT / "schemas/pr-triage-report.schema.json"
HUMAN_GATES_PATH = ROOT / "config/human-gates.yaml"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
FULL_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PR_URL = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*$")
SAFE_PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[^\x00\r\n]+$")

CHANGE_CLASSES = ("CLASS_RECORD", "CLASS_DOCS", "CLASS_CODE", "CLASS_CONTRACT")
RECOMMENDATIONS = (
    "MERGE_CANDIDATE",
    "NEEDS_REBASE",
    "NEEDS_CI_FIX",
    "SUPERSEDED_CANDIDATE",
    "HUMAN_JUDGMENT",
)
CHECK_STATUSES = ("GREEN", "RED", "PENDING", "UNKNOWN")
TASK_STATUSES = ("BACKLOG", "READY", "IN_PROGRESS", "BLOCKED", "DONE", "UNKNOWN")


class PRTriageError(ValueError):
    """Raised when PR metadata cannot be converted to the closed contract."""


def _error(message: str, remediation: str) -> PRTriageError:
    return PRTriageError(f"{message}; remediation: {remediation}")


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise _error("observation timestamp must be a string", "supply an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error("observation timestamp is invalid", "use ISO-8601 date-time") from exc
    if parsed.tzinfo is None:
        raise _error("observation timestamp has no timezone", "use UTC or an explicit offset")
    return value


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise _error(f"{label} must be a timestamp", "retain GitHub's ISO-8601 metadata")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error(f"{label} is invalid", "retain an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise _error(f"{label} has no timezone", "retain UTC or an explicit offset")
    return parsed.astimezone(timezone.utc)


def _sha(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or SHA40.fullmatch(value) is None:
        raise _error(f"{label} is not an immutable commit", "retain a 40-character lowercase SHA")
    return value


def _full_name(value: object, label: str) -> str:
    if not isinstance(value, str) or FULL_NAME.fullmatch(value) is None:
        raise _error(f"{label} is not an owner/name", "use the manifest repository full name")
    return value


def _path_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise _error(f"{label} must be a list", "retain changed file paths only")
    paths: set[str] = set()
    for path in value:
        if isinstance(path, Mapping):
            path = path.get("path")
        if not isinstance(path, str) or not path or SAFE_PATH.fullmatch(path) is None:
            raise _error(f"{label} contains an unsafe path", "retain relative changed paths without traversal")
        paths.add(path.replace("\\", "/"))
    return sorted(paths)


def _load_manifest_repositories() -> list[dict[str, str]]:
    manifest = load_yaml(MANIFEST_PATH)
    repositories = manifest.get("repositories") if isinstance(manifest, Mapping) else None
    if not isinstance(repositories, list):
        raise _error("manifest repositories are missing", "repair config/repositories.yaml")
    result = []
    for repository in repositories:
        if not isinstance(repository, Mapping):
            raise _error("manifest repository is not an object", "repair config/repositories.yaml")
        result.append(
            {
                "repository": str(repository["id"]),
                "full_name": _full_name(repository.get("full_name"), "manifest full_name"),
                "default_branch": str(repository.get("default_branch", "main")),
                "source_commit": _sha(repository.get("observed_commit"), "manifest observed_commit"),
            }
        )
    parent_commit = _git_output(["git", "rev-parse", "HEAD"])
    result.append(
        {
            "repository": "agentic-art-orchestration",
            "full_name": "masa-san-jp/agentic-art-orchestration",
            "default_branch": "main",
            "source_commit": _sha(parent_commit, "parent HEAD"),
        }
    )
    return sorted(result, key=lambda item: item["repository"])


def _git_output(command: list[str]) -> str:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise _error("could not observe the parent commit", "run from a valid Git checkout")
    value = completed.stdout.strip()
    if not value:
        raise _error("parent commit observation was empty", "run from a valid Git checkout")
    return value


def _queue_tasks(queue_path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    queue_bytes = queue_path.read_bytes()
    queue = load_yaml(queue_path)
    tasks = queue.get("tasks") if isinstance(queue, Mapping) else None
    if not isinstance(tasks, list):
        raise _error("task queue is invalid", "retain execution/task-queue.yaml as the SSOT")
    by_issue: dict[str, dict[str, Any]] = {}
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        issue = task.get("issue_ssot")
        task_id = task.get("id")
        if isinstance(issue, str) and isinstance(task_id, str):
            by_issue[issue] = {"id": task_id, "status": task.get("status", "UNKNOWN")}
    import hashlib

    return by_issue, hashlib.sha256(queue_bytes).hexdigest()


def _classify_paths(paths: list[str]) -> str:
    if not paths:
        return "CLASS_CODE"
    classes: set[str] = set()
    gates = load_yaml(HUMAN_GATES_PATH)
    merge_classes = gates.get("merge_classes") if isinstance(gates, Mapping) else None
    if not isinstance(merge_classes, Mapping):
        raise _error("merge classes are missing", "restore config/human-gates.yaml")
    for path in paths:
        matches = []
        for class_name, definition in merge_classes.items():
            prefixes = definition.get("path_prefixes", []) if isinstance(definition, Mapping) else []
            if any(path == prefix or path.startswith(prefix) for prefix in prefixes if isinstance(prefix, str)):
                matches.append(class_name)
        classes.add(matches[0] if len(matches) == 1 else "CLASS_CODE")
    for candidate in ("CLASS_CONTRACT", "CLASS_CODE", "CLASS_DOCS", "CLASS_RECORD"):
        if candidate in classes:
            return candidate
    return "CLASS_CODE"


def _check_summary(value: object) -> dict[str, int]:
    entries = value if isinstance(value, list) else []
    passed = failed = pending = 0
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        status = str(entry.get("status", "")).upper()
        conclusion = str(entry.get("conclusion", "")).upper()
        if conclusion in {"SUCCESS", "NEUTRAL", "SKIPPED"}:
            passed += 1
        elif conclusion in {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}:
            failed += 1
        elif status in {"QUEUED", "IN_PROGRESS", "PENDING", "REQUESTED", "WAITING"} or conclusion in {"PENDING", "QUEUED"}:
            pending += 1
        else:
            pending += 1
    if failed:
        status = "RED"
    elif pending:
        status = "PENDING"
    elif passed:
        status = "GREEN"
    else:
        status = "UNKNOWN"
    return {"status": status, "total": len(entries), "passed": passed, "failed": failed, "pending": pending}


def _conflict(value: object) -> str:
    normalized = str(value or "").upper()
    if normalized == "MERGEABLE":
        return "NO"
    if normalized == "CONFLICTING":
        return "YES"
    return "UNKNOWN"


def _issue_reference(raw: Mapping[str, object]) -> str | None:
    explicit = raw.get("issue_ssot")
    if isinstance(explicit, str) and explicit:
        return explicit
    references = raw.get("closingIssuesReferences", raw.get("issue_references", []))
    if not isinstance(references, list):
        return None
    urls = []
    for reference in references:
        if isinstance(reference, str):
            urls.append(reference)
        elif isinstance(reference, Mapping) and isinstance(reference.get("url"), str):
            urls.append(reference["url"])
    return sorted(urls)[0] if urls else None


def _task_metadata(raw: Mapping[str, object], queue_tasks: Mapping[str, Mapping[str, Any]]) -> tuple[str | None, str, str | None]:
    issue_ssot = _issue_reference(raw)
    explicit_task = raw.get("task_id")
    task = queue_tasks.get(issue_ssot) if issue_ssot else None
    task_id = explicit_task if isinstance(explicit_task, str) else task.get("id") if task else None
    task_status = task.get("status", "UNKNOWN") if task else raw.get("task_status", "UNKNOWN")
    if task_id is not None and not isinstance(task_id, str):
        raise _error("task_id is invalid", "use the execution queue task ID")
    if task_status not in TASK_STATUSES:
        task_status = "UNKNOWN"
    return task_id, task_status, issue_ssot


def _one_pr(raw: Mapping[str, object], repositories: Mapping[str, Mapping[str, str]], queue_tasks: Mapping[str, Mapping[str, Any]], observed_at: str) -> dict[str, object]:
    repository = raw.get("repository")
    if not isinstance(repository, str) or repository not in repositories:
        full_name = raw.get("full_name")
        matches = [key for key, item in repositories.items() if item.get("full_name") == full_name]
        repository = matches[0] if len(matches) == 1 else repository
    if not isinstance(repository, str) or repository not in repositories:
        raise _error("PR repository is not in the triage source", "use a manifest repository ID")
    meta = repositories[repository]
    number = raw.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise _error("PR number is invalid", "retain GitHub PR metadata")
    title = raw.get("title")
    if not isinstance(title, str) or not title:
        raise _error("PR title is missing", "retain the PR title without its body")
    url = raw.get("url")
    if not isinstance(url, str) or PR_URL.fullmatch(url) is None:
        raise _error("PR URL is invalid", "retain the canonical GitHub pull URL")
    source_commit = _sha(raw.get("source_commit", meta.get("source_commit")), "source_commit")
    head_sha = _sha(raw.get("headRefOid", raw.get("head_sha")), "head_sha", nullable=True)
    base_sha = _sha(raw.get("baseRefOid", raw.get("base_sha")), "base_sha", nullable=True)
    created_at = raw.get("createdAt", raw.get("created_at"))
    created_dt = _parse_timestamp(created_at, "created_at")
    observed_dt = _parse_timestamp(observed_at, "observed_at")
    age_days = max(0, (observed_dt - created_dt).days)
    paths = _path_list(raw.get("files", raw.get("changed_paths", [])), "changed_paths")
    checks = raw.get("checks") if isinstance(raw.get("checks"), Mapping) else _check_summary(raw.get("statusCheckRollup", []))
    if not isinstance(checks, Mapping) or checks.get("status") not in CHECK_STATUSES:
        raise _error("PR checks metadata is invalid", "use GREEN, RED, PENDING, or UNKNOWN")
    check_summary = {
        "status": checks["status"],
        "total": int(checks.get("total", 0)),
        "passed": int(checks.get("passed", 0)),
        "failed": int(checks.get("failed", 0)),
        "pending": int(checks.get("pending", 0)),
    }
    conflict = raw.get("conflict") if raw.get("conflict") in {"YES", "NO", "UNKNOWN"} else _conflict(raw.get("mergeable"))
    task_id, task_status, issue_ssot = _task_metadata(raw, queue_tasks)
    superseded_reason = None
    if head_sha is not None and base_sha is not None and head_sha == base_sha:
        superseded_reason = "HEAD_REACHED_BASE"
    elif bool(raw.get("included_in_later_commit")) and task_status == "DONE":
        superseded_reason = "TASK_DONE_LATER_COMMIT"
    if superseded_reason:
        recommendation = "SUPERSEDED_CANDIDATE"
    elif conflict == "YES":
        recommendation = "NEEDS_REBASE"
    elif check_summary["status"] == "RED":
        recommendation = "NEEDS_CI_FIX"
    elif check_summary["status"] == "GREEN" and conflict == "NO":
        recommendation = "MERGE_CANDIDATE"
    else:
        recommendation = "HUMAN_JUDGMENT"
    return {
        "repository": repository,
        "source_commit": source_commit,
        "number": number,
        "title": title,
        "url": url,
        "base_branch": str(raw.get("baseRefName", raw.get("base_branch", meta.get("default_branch", "main")))),
        "head_branch": str(raw.get("headRefName", raw.get("head_branch", "unknown"))),
        "head_sha": head_sha,
        "base_sha": base_sha,
        "created_at": created_at,
        "age_days": age_days,
        "checks": check_summary,
        "conflict": conflict,
        "changed_paths": paths,
        "change_class": _classify_paths(paths),
        "task_id": task_id,
        "task_status": task_status,
        "issue_ssot": issue_ssot,
        "superseded_reason": superseded_reason,
        "recommendation": recommendation,
    }


def build_report(payload: Mapping[str, object], queue_path: Path = QUEUE_PATH) -> dict[str, object]:
    """Convert a fixture/live envelope into the closed triage report."""
    if not isinstance(payload, Mapping):
        raise _error("PR triage input is not an object", "use the fixture envelope or live metadata")
    source = payload.get("source")
    if not isinstance(source, Mapping) or source.get("kind") not in {"fixture", "live", "json"}:
        raise _error("PR triage source is invalid", "use fixture or live metadata")
    observed_at = _timestamp(source.get("observed_at"))
    raw_repositories = payload.get("repositories")
    if not isinstance(raw_repositories, list) or not raw_repositories:
        raise _error("PR triage repositories are missing", "include every manifest repository in the envelope")
    repositories: dict[str, dict[str, str]] = {}
    for index, item in enumerate(raw_repositories):
        if not isinstance(item, Mapping):
            raise _error(f"repositories[{index}] is invalid", "include repository metadata")
        repo_id = item.get("repository", item.get("id"))
        if not isinstance(repo_id, str) or not repo_id:
            raise _error("repository ID is missing", "use the manifest repository ID")
        if repo_id in repositories:
            raise _error(f"duplicate repository {repo_id}", "retain one source entry per repository")
        repositories[repo_id] = {
            "full_name": _full_name(item.get("full_name"), f"repositories[{index}].full_name"),
            "default_branch": str(item.get("default_branch", "main")),
            "source_commit": _sha(item.get("source_commit"), f"repositories[{index}].source_commit"),
        }
    raw_prs = payload.get("pull_requests", [])
    if not isinstance(raw_prs, list):
        raise _error("pull_requests must be a list", "retain one metadata object per open PR")
    queue_tasks, queue_sha = _queue_tasks(queue_path)
    records = [_one_pr(item, repositories, queue_tasks, observed_at) for item in raw_prs if isinstance(item, Mapping)]
    if len(records) != len(raw_prs):
        raise _error("pull_requests contains a non-object", "retain GitHub PR metadata only")
    records.sort(key=lambda item: (str(item["repository"]), int(item["number"])))
    class_counts = {key: sum(item["change_class"] == key for item in records) for key in CHANGE_CLASSES}
    recommendation_counts = {key: sum(item["recommendation"] == key for item in records) for key in RECOMMENDATIONS}
    source_out = {
        "kind": source["kind"],
        "locator": str(source.get("locator", "")),
        "observed_at": observed_at,
        "repositories": [
            {"repository": key, **repositories[key]}
            for key in sorted(repositories)
        ],
    }
    report = {
        "contract_version": "pr-triage-report/v1",
        "source": source_out,
        "queue": {"path": str(queue_path.relative_to(ROOT)) if queue_path.is_relative_to(ROOT) else str(queue_path), "sha256": queue_sha},
        "pull_requests": records,
        "summary": {
            "repository_count": len(repositories),
            "pull_request_count": len(records),
            "change_class_counts": class_counts,
            "recommendation_counts": recommendation_counts,
        },
        "remote_operations": ["READ"] if source["kind"] == "live" else [],
    }
    errors = _schema_errors(report, load_json(SCHEMA_PATH), "pr-triage-report")
    if errors:
        raise PRTriageError("\n".join(errors))
    return report


def _gh_json(repository: str) -> list[dict[str, object]]:
    command = [
        "gh", "pr", "list", "--repo", repository, "--state", "open", "--limit", "1000",
        "--json", "number,title,url,headRefName,baseRefName,headRefOid,baseRefOid,createdAt,statusCheckRollup,mergeable,files,closingIssuesReferences",
    ]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise _error(f"GitHub PR metadata read failed for {repository}", "restore read-only gh authentication or use a fixture")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise _error(f"GitHub PR metadata was not JSON for {repository}", "use gh JSON output or a fixture") from exc
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise _error(f"GitHub PR metadata shape was invalid for {repository}", "retain a list of PR metadata objects")
    return [dict(item) for item in value]


def build_live_payload(observed_at: str) -> dict[str, object]:
    repositories = _load_manifest_repositories()
    pull_requests: list[dict[str, object]] = []
    for repository in repositories:
        for item in _gh_json(repository["full_name"]):
            pull_requests.append({**item, "repository": repository["repository"]})
    return {
        "source": {"kind": "live", "locator": "gh pr list --state open --json metadata", "observed_at": observed_at},
        "repositories": repositories,
        "pull_requests": pull_requests,
    }


def _render(report: Mapping[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _path(value: Path) -> Path:
    return value if value.is_absolute() else ROOT / value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="networkless PR triage envelope")
    source.add_argument("--live", action="store_true", help="read all manifest repository open PRs through gh")
    parser.add_argument("--observed-at", help="fixed observation timestamp; required for live mode")
    parser.add_argument("--queue", type=Path, default=QUEUE_PATH)
    parser.add_argument("--output", type=Path, help="optional report output path")
    parser.add_argument("--check", action="store_true", help="prove schema validity and repeated byte identity")
    args = parser.parse_args(argv)
    try:
        if args.live:
            if not args.observed_at:
                raise _error("live mode requires --observed-at", "supply a fixed ISO-8601 read timestamp")
            payload = build_live_payload(args.observed_at)
        else:
            fixture_path = _path(args.fixture)
            payload = load_json(fixture_path)
        report = build_report(payload, _path(args.queue))
        rendered = _render(report)
        if args.check:
            repeated = build_report(copy.deepcopy(payload), _path(args.queue))
            if rendered != _render(repeated):
                raise _error("repeated report bytes differ", "keep source metadata and sorting deterministic")
        if args.output:
            output = _path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered, encoding="utf-8")
        sys.stdout.write(rendered)
        return 0
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
