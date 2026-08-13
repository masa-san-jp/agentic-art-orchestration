#!/usr/bin/env python3
"""Run the read-only repository-update portion of orchestration startup."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate import (  # noqa: E402
    STARTUP_CAPABILITIES,
    STARTUP_STEPS,
    _schema_errors,
    load_json,
    load_yaml,
    validate,
)
from tools.workspace import (  # noqa: E402
    DEFAULT_OFFLINE_FIXTURE_ROOT,
    ensure_offline_remotes,
    load_manifest,
    resolve_path,
)


DEFAULT_MANIFEST = ROOT / "config/repositories.yaml"
DEFAULT_SNAPSHOT = ROOT / "data/snapshot.json"
DEFAULT_OUTPUT = ROOT / "data/startup.json"
REPORT_SCHEMA = ROOT / "schemas/startup-report.schema.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
EPOCH = "1970-01-01T00:00:00Z"


class StartupError(ValueError):
    """Startup inputs or read-only observations are unsafe or incomplete."""


def _error(detail: str, remediation: str) -> StartupError:
    return StartupError(f"startup: {detail}; remediation: {remediation}")


def _run_git(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run Git without a shell and return only structured stdout/stderr."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _parent_commit() -> tuple[str, str]:
    code, commit, _ = _run_git(["rev-parse", "HEAD"], ROOT)
    if code or not SHA40.fullmatch(commit):
        raise _error("parent HEAD is not an immutable commit", "run startup inside a valid parent Git checkout")
    code, timestamp, _ = _run_git(["show", "-s", "--format=%cI", "HEAD"], ROOT)
    if code or not timestamp:
        return commit, EPOCH
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return commit, EPOCH
        return commit, parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return commit, EPOCH


def _snapshot_pins(snapshot_path: Path, manifest: dict) -> dict[str, str]:
    """Load only qualified commit metadata from the immutable snapshot."""
    if not snapshot_path.is_file():
        raise _error("qualified snapshot is missing", "run workspace.py snapshot and qualify the resulting snapshot")
    try:
        snapshot = load_json(snapshot_path)
    except (OSError, ValueError) as exc:
        raise _error("qualified snapshot cannot be read", "repair or regenerate data/snapshot.json") from exc
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("repositories"), list):
        raise _error("qualified snapshot has no repository records", "regenerate data/snapshot.json from the manifest workspace")

    manifest_ids = {repository["id"] for repository in manifest["repositories"]}
    records = {record.get("id"): record for record in snapshot["repositories"] if isinstance(record, dict)}
    if set(records) != manifest_ids:
        raise _error("qualified snapshot repository set differs from manifest", "qualify every manifest repository in one snapshot")

    pins: dict[str, str] = {}
    for repository in manifest["repositories"]:
        repository_id = repository["id"]
        record = records[repository_id]
        pin = record.get("manifest_observed_commit")
        if not SHA40.fullmatch(str(pin)) or pin != repository.get("observed_commit"):
            raise _error(
                f"qualified snapshot pin mismatch for {repository_id}",
                "review the manifest pin and regenerate a matching qualified snapshot",
            )
        pins[repository_id] = pin
    return pins


def _remote_head(remote: str, default_branch: str) -> str | None:
    """Observe one remote ref without fetch, checkout, or ref mutation."""
    code, stdout, _ = _run_git(["ls-remote", remote, f"refs/heads/{default_branch}"], ROOT)
    if code or not stdout:
        return None
    rows = [line.split() for line in stdout.splitlines() if line.split()]
    if len(rows) != 1 or len(rows[0]) < 2 or rows[0][1] != f"refs/heads/{default_branch}":
        return None
    return rows[0][0] if SHA40.fullmatch(rows[0][0]) else None


def observe_repository(repository: dict, qualified_commit: str, remote: str, timestamp: str) -> dict:
    """Return sanitized remote-vs-qualified metadata for one manifest entry."""
    remote_commit = _remote_head(remote, repository["default_branch"])
    if remote_commit is None:
        return {
            "repository": repository["id"],
            "qualified_commit": qualified_commit,
            "remote_observed_commit": None,
            "observation_timestamp": timestamp,
            "drift": "UNAVAILABLE",
            "pinned_for_use": True,
        }
    return {
        "repository": repository["id"],
        "qualified_commit": qualified_commit,
        "remote_observed_commit": remote_commit,
        "observation_timestamp": timestamp,
        "drift": "CLEAN" if remote_commit == qualified_commit else "UPDATE_CANDIDATE",
        "pinned_for_use": True,
    }


def _step(step_id: str, status: str, blocking: bool = False, finding_codes: list[str] | None = None) -> dict:
    return {
        "step_id": step_id,
        "status": status,
        "blocking": blocking,
        "finding_codes": sorted(set(finding_codes or [])),
    }


def _capabilities(status: str, findings: list[str]) -> list[dict]:
    restricted_create = status != "READY"
    records = []
    for capability in STARTUP_CAPABILITIES:
        if capability in {"child_repository_mutation", "drive_update_delete_share", "github_issue_update_close_delete_comment_label", "branch_commit_pull_request_merge_release"}:
            capability_status = "BLOCKED"
        elif capability in {"drive_create", "github_issue_create"} and restricted_create:
            capability_status = "RESTRICTED"
        elif status == "BLOCKED":
            capability_status = "BLOCKED"
        else:
            capability_status = "ALLOWED"
        records.append(
            {
                "capability": capability,
                "status": capability_status,
                "reason_codes": sorted(set(findings)) if capability_status != "ALLOWED" else [],
            }
        )
    return records


def validate_report(report: dict) -> list[str]:
    """Validate the closed schema and startup-specific ordering semantics."""
    schema = load_json(REPORT_SCHEMA)
    errors = _schema_errors(report, schema)
    if not isinstance(report, dict):
        return errors
    steps = report.get("ordered_steps", [])
    if [step.get("step_id") for step in steps if isinstance(step, dict)] != STARTUP_STEPS:
        errors.append("startup report ordered_steps do not preserve the declared preflight order")
    repositories = report.get("repositories", [])
    if any(record.get("pinned_for_use") is not True for record in repositories if isinstance(record, dict)):
        errors.append("startup report contains a repository that is not pinned for use")
    return errors


def build_startup_report(
    manifest: dict,
    snapshot_path: Path = DEFAULT_SNAPSHOT,
    offline_fixture: bool = False,
    fixture_root: Path = DEFAULT_OFFLINE_FIXTURE_ROOT,
    run_id: str | None = None,
    agent_client: str = "Codex",
) -> dict:
    """Build a metadata-only report; only offline fixture remotes may be created."""
    if agent_client not in {"Codex", "Claude Code"}:
        raise _error("agent_client is not supported", "choose Codex or Claude Code")
    parent_commit, timestamp = _parent_commit()
    run_id = run_id or f"startup:{parent_commit}"
    if not STABLE_ID.fullmatch(run_id):
        raise _error("run_id is not stable", "use letters, digits, dot, underscore, colon, or hyphen")
    pins = _snapshot_pins(snapshot_path, manifest)
    offline_remotes = None
    if offline_fixture:
        offline_remotes, _ = ensure_offline_remotes(manifest, fixture_root)

    repositories = []
    for repository in manifest["repositories"]:
        remote = str(offline_remotes / f"{repository['id']}.git") if offline_remotes else repository["url"]
        repositories.append(observe_repository(repository, pins[repository["id"]], remote, timestamp))

    findings: list[dict] = []
    finding_codes: list[str] = []
    for record in repositories:
        if record["drift"] == "UPDATE_CANDIDATE":
            code = "remote_update_candidate"
            finding_codes.append(code)
            findings.append({"code": code, "severity": "WARNING", "source": "repository"})
        elif record["drift"] == "UNAVAILABLE":
            code = "remote_observation_unavailable"
            finding_codes.append(code)
            findings.append({"code": code, "severity": "WARNING", "source": "repository"})

    findings = list({(item["code"], item["source"]): item for item in findings}.values())
    finding_codes = sorted({item["code"] for item in findings})

    findings = list({(finding["code"], finding["source"]): finding for finding in findings}.values())
    status = "READY" if not finding_codes else "READY_WITH_FINDINGS"
    observe_status = "PASSED" if not finding_codes else "FINDINGS"
    ordered_steps = [
        _step("validate_parent_configuration", "PASSED"),
        _step("observe_remote_heads", observe_status, False, finding_codes),
        _step("guard_pinned_workspaces", "NOT_RUN"),
        _step("select_qualified_snapshot", "PASSED"),
        _step("materialize_snapshot", "NOT_RUN"),
        _step("collect_status", "NOT_RUN"),
        _step("run_audit", "NOT_RUN"),
        _step("run_security", "NOT_RUN"),
        _step("decide_capabilities", "PASSED"),
    ]
    report = {
        "contract_version": "startup-report/v1",
        "run_id": run_id,
        "generated_at": timestamp,
        "profile": "initial-operations",
        "agent_client": agent_client,
        "status": status,
        "parent_commit": parent_commit,
        "ordered_steps": ordered_steps,
        "repositories": repositories,
        "workspace_guard": {"status": "NOT_RUN", "checked_repositories": [], "finding_codes": []},
        "findings": sorted(findings, key=lambda item: (item["code"], item["source"])),
        "capabilities": _capabilities(status, finding_codes),
        "remediation": [
            "review remote_update_candidate before changing a manifest pin" if "remote_update_candidate" in finding_codes else None,
            "retry remote observation before claiming the remote head is current" if "remote_observation_unavailable" in finding_codes else None,
        ],
        "privacy": {
            "raw_conversation_stored": False,
            "credentials_stored": False,
            "raw_remote_response_stored": False,
            "drive_content_stored": False,
            "direct_identifiers_stored": False,
        },
        "remote_operations": [],
    }
    report["remediation"] = [item for item in report["remediation"] if item]
    errors = validate_report(report)
    if errors:
        raise _error("generated startup report is invalid", "; ".join(errors))
    return report


def _write_or_check(report: dict, output: Path, check: bool) -> dict:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if check:
        if not output.is_file():
            raise _error("startup report is missing", "run startup without --check to materialize the report")
        if output.read_text(encoding="utf-8") != rendered:
            raise _error("startup report is stale", "rerun startup without --check to regenerate the report")
        changed = False
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        changed = not output.is_file() or output.read_text(encoding="utf-8") != rendered
        output.write_text(rendered, encoding="utf-8")
    return {
        "command": "startup",
        "changed": changed,
        "output": str(output),
        "status": report["status"],
        "repository_count": len(report["repositories"]),
        "finding_count": len(report["findings"]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Observe manifest repository heads without mutation")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--offline-fixture", action="store_true")
    parser.add_argument("--fixture-root", type=Path, default=DEFAULT_OFFLINE_FIXTURE_ROOT)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run-id")
    parser.add_argument("--agent-client", default="Codex")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        errors = validate()
        if errors:
            raise _error("parent configuration is invalid", "run tools/validate.py --check and repair the reported boundary")
        manifest = load_manifest()
        report = build_startup_report(
            manifest,
            resolve_path(args.snapshot),
            args.offline_fixture,
            resolve_path(args.fixture_root),
            args.run_id,
            args.agent_client,
        )
        result = _write_or_check(report, resolve_path(args.output), args.check)
    except (OSError, StartupError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
