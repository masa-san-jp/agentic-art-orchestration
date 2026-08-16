#!/usr/bin/env python3
"""Run the read-only repository-update portion of orchestration startup."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
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
from tools import audit as audit_tool  # noqa: E402
from tools import security as security_tool  # noqa: E402
from tools import status as status_tool  # noqa: E402
from tools.workspace import (  # noqa: E402
    DEFAULT_OFFLINE_FIXTURE_ROOT,
    ensure_offline_remotes,
    guard_workspace,
    init_workspace,
    load_manifest,
    read_repo_status,
    resolve_path,
    resolve_workspace_root,
)


DEFAULT_MANIFEST = ROOT / "config/repositories.yaml"
DEFAULT_SNAPSHOT = ROOT / "data/snapshot.json"
DEFAULT_OUTPUT = ROOT / "data/startup.json"
REPORT_SCHEMA = ROOT / "schemas/startup-report.schema.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
EPOCH = "1970-01-01T00:00:00Z"
CRITICAL_AUDIT_CODES = {
    "schema-drift",
    "consent",
    "forbidden-data",
    "invalid-signal",
    "stale-pin",
    "secret",
    "unapproved-export",
}


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


def _capabilities(status: str, findings: list[str] | list[dict]) -> list[dict]:
    finding_records = [
        finding if isinstance(finding, dict) else {"code": finding, "severity": "WARNING"}
        for finding in findings
    ]
    finding_codes = [finding.get("code") for finding in finding_records if isinstance(finding.get("code"), str)]
    capability_policy = load_yaml(ROOT / "config/startup-policy.yaml")
    policy_capabilities = capability_policy.get("capabilities", []) if isinstance(capability_policy, dict) else []
    policy_map = {
        item.get("id"): item
        for item in policy_capabilities
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    parent_policy = policy_map.get("branch_commit_pull_request", {})
    allowed_severities = set(parent_policy.get("allowed_finding_severities", []))
    require_nonempty = parent_policy.get("require_nonempty_findings_for_ready_with_findings") is True
    restricted_create = status != "READY"
    parent_control_plane_allowed = status == "READY" or (
        status == "READY_WITH_FINDINGS"
        and (bool(finding_records) or not require_nonempty)
        and all(finding.get("severity") in allowed_severities for finding in finding_records)
    )
    records = []
    for capability in STARTUP_CAPABILITIES:
        if capability in {
            "child_repository_mutation",
            "drive_update_delete_share",
            "github_issue_update_close_delete_comment_label",
            "merge_release_tag",
        }:
            capability_status = "BLOCKED"
        elif status == "BLOCKED":
            capability_status = "BLOCKED"
        elif capability == "branch_commit_pull_request":
            capability_status = "ALLOWED" if parent_control_plane_allowed else "RESTRICTED"
        elif capability in {"drive_create", "github_issue_create"} and restricted_create:
            capability_status = "RESTRICTED"
        else:
            capability_status = "ALLOWED"
        records.append(
            {
                "capability": capability,
                "status": capability_status,
                "reason_codes": sorted(set(finding_codes))
                if capability_status != "ALLOWED"
                or (capability == "branch_commit_pull_request" and finding_records)
                else [],
            }
        )
    return records


def _issue_candidates(
    manifest: dict,
    repositories: list[dict],
    audit_result: dict,
    status: str,
    status_findings: bool = False,
) -> list[dict]:
    """Emit deduplicated, privacy-safe candidates without creating Issues."""
    repository_ids = {repository["id"] for repository in manifest["repositories"]}
    candidates: dict[str, dict] = {}

    def add(source_kind: str, finding_code: str, target: str) -> None:
        if target not in repository_ids:
            target = "agentic-art-orchestration"
        identity = {"source_kind": source_kind, "finding_code": finding_code, "target": target}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]
        key = f"startup:{source_kind}:{digest}"
        candidates.setdefault(
            key,
            {
                "candidate_id": f"startup:issue:{digest}",
                "source_kind": source_kind,
                "finding_code": finding_code,
                "deduplication_key": key,
                "target_repository": target,
                "privacy_safe_summary": f"Startup observed {finding_code} for {target}; review the owning repository boundary.",
                "creation_permitted": status == "READY",
                "human_gate": True,
                "side_effect": "NONE",
            },
        )

    for repository in repositories:
        if repository["drift"] != "CLEAN":
            add("repository-update", "remote_update_candidate" if repository["drift"] == "UPDATE_CANDIDATE" else "remote_observation_unavailable", repository["repository"])
    if status_findings:
        add("audit", "audit_finding", "agentic-art-orchestration")
    for finding in audit_result.get("findings", []):
        if isinstance(finding, dict) and isinstance(finding.get("code"), str):
            subject = finding.get("subject") if isinstance(finding.get("subject"), str) else "agentic-art-orchestration"
            add("audit", finding["code"], subject)
    return [candidates[key] for key in sorted(candidates)]


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
    capabilities = report.get("capabilities", [])
    if report.get("status") == "BLOCKED" and any(
        isinstance(capability, dict) and capability.get("status") != "BLOCKED"
        for capability in capabilities
    ):
        errors.append("BLOCKED startup report exposes a non-blocked capability")
    capability_statuses = {
        capability.get("capability"): capability.get("status")
        for capability in capabilities
        if isinstance(capability, dict)
    }
    always_blocked = {
        "child_repository_mutation",
        "drive_update_delete_share",
        "github_issue_update_close_delete_comment_label",
        "merge_release_tag",
    }
    if report.get("status") != "BLOCKED":
        exposed = sorted(
            capability for capability in always_blocked
            if capability_statuses.get(capability) != "BLOCKED"
        )
        if exposed:
            errors.append(f"startup report exposes always-blocked capabilities: {', '.join(exposed)}")
    findings = [item for item in report.get("findings", []) if isinstance(item, dict)]
    if report.get("status") == "READY" and findings:
        errors.append("READY startup report contains findings")
    if report.get("status") == "READY_WITH_FINDINGS" and not findings:
        errors.append("READY_WITH_FINDINGS report must contain findings")
    if report.get("status") != "BLOCKED" and any(item.get("severity") == "CRITICAL" for item in findings):
        errors.append("non-blocked startup report contains a critical finding")
    if report.get("status") != "BLOCKED":
        policy = load_yaml(ROOT / "config/startup-policy.yaml")
        policy_capabilities = policy.get("capabilities", []) if isinstance(policy, dict) else []
        policy_map = {
            item.get("id"): item
            for item in policy_capabilities
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        parent_policy = policy_map.get("branch_commit_pull_request", {})
        allowed_severities = set(parent_policy.get("allowed_finding_severities", []))
        require_nonempty = parent_policy.get("require_nonempty_findings_for_ready_with_findings") is True
        if report.get("status") == "READY":
            expected_parent_status = "ALLOWED"
        elif (
            findings
            and all(item.get("severity") in allowed_severities for item in findings)
            and (bool(findings) or not require_nonempty)
        ):
            expected_parent_status = "ALLOWED"
        else:
            expected_parent_status = "RESTRICTED"
        if capability_statuses.get("branch_commit_pull_request") != expected_parent_status:
            errors.append("startup report has an unsafe parent control-plane capability decision")
    candidates = report.get("issue_candidates", [])
    deduplication_keys = [
        candidate.get("deduplication_key")
        for candidate in candidates
        if isinstance(candidate, dict)
    ]
    if len(deduplication_keys) != len(set(deduplication_keys)):
        errors.append("startup report contains duplicate Issue candidate deduplication keys")
    return errors


def build_startup_report(
    manifest: dict,
    snapshot_path: Path = DEFAULT_SNAPSHOT,
    offline_fixture: bool = False,
    fixture_root: Path = DEFAULT_OFFLINE_FIXTURE_ROOT,
    run_id: str | None = None,
    agent_client: str = "Codex",
    workspace_root: Path | None = None,
) -> dict:
    """Build a metadata-only report; only offline fixture remotes may be created."""
    if agent_client not in {"Codex", "Claude Code"}:
        raise _error("agent_client is not supported", "choose Codex or Claude Code")
    parent_commit, timestamp = _parent_commit()
    run_id = run_id or f"startup:{parent_commit}"
    if not STABLE_ID.fullmatch(run_id):
        raise _error("run_id is not stable", "use letters, digits, dot, underscore, colon, or hyphen")
    pins = _snapshot_pins(snapshot_path, manifest)
    snapshot = load_json(snapshot_path)
    if not isinstance(snapshot, dict):
        raise _error("qualified snapshot is not an object", "regenerate data/snapshot.json")
    offline_remotes = None
    if offline_fixture:
        offline_remotes, _ = ensure_offline_remotes(manifest, fixture_root)

    repositories = []
    for repository in manifest["repositories"]:
        remote = str(offline_remotes / f"{repository['id']}.git") if offline_remotes else repository["url"]
        repositories.append(observe_repository(repository, pins[repository["id"]], remote, timestamp))

    findings: list[dict] = []

    def add_finding(code: str, severity: str, source: str) -> None:
        finding = {"code": code, "severity": severity, "source": source}
        if finding not in findings:
            findings.append(finding)

    for record in repositories:
        if record["drift"] == "UPDATE_CANDIDATE":
            add_finding("remote_update_candidate", "WARNING", "repository")
        elif record["drift"] == "UNAVAILABLE":
            add_finding("remote_observation_unavailable", "WARNING", "repository")

    if offline_fixture:
        resolved_workspace_root = (
            workspace_root.resolve()
            if workspace_root is not None
            else (fixture_root / "workspace").resolve()
        )
        # The fixture workspace is test infrastructure only. Never initialize or
        # repair a caller-supplied checkout; an existing fixture is guarded as-is.
        if workspace_root is None and not resolved_workspace_root.exists():
            init_workspace(manifest, resolved_workspace_root, True, fixture_root)
    else:
        resolved_workspace_root = resolve_workspace_root(
            manifest,
            str(workspace_root) if workspace_root is not None else None,
        )
    guard_offline = offline_fixture
    guard = guard_workspace(manifest, resolved_workspace_root, guard_offline, fixture_root)
    guard_codes = sorted({code for repository in guard["repositories"] for code in repository["reason_codes"]})
    guard_blocked = bool(guard["blocked_count"])
    if guard_blocked:
        add_finding("workspace_guard_blocked", "CRITICAL", "workspace")

    queue = load_yaml(ROOT / "execution/task-queue.yaml")
    state = load_yaml(ROOT / "execution/state.yaml")
    live_repositories = [read_repo_status(repository, resolved_workspace_root) for repository in manifest["repositories"]]
    manifest_hash = status_tool.sha256_text(status_tool.canonical_json(manifest))
    portfolio_status = status_tool.build_status(snapshot, queue, state, live_repositories, manifest_hash)
    status_has_findings = bool(portfolio_status["blockers"] or portfolio_status["drift"]["items"])
    if status_has_findings:
        add_finding("audit_finding", "WARNING", "audit")
    compatibility = portfolio_status.get("compatibility")
    if isinstance(compatibility, dict) and compatibility.get("status") == "INCOMPATIBLE":
        add_finding("schema_major_mismatch", "CRITICAL", "audit")

    signals, requirements = audit_tool._load_signals_and_requirements()
    tested_boundaries = {
        boundary: (ROOT / path).is_file()
        for boundary, path in audit_tool.EXPECTED_BOUNDARIES.items()
    }
    audit_result = audit_tool.build_audit(
        manifest,
        snapshot,
        queue,
        state,
        signals,
        requirements,
        tested_boundaries,
    )
    audit_has_findings = bool(audit_result["findings"])
    if audit_has_findings:
        add_finding("audit_finding", "WARNING", "audit")
        for audit_finding in audit_result["findings"]:
            if not isinstance(audit_finding, dict) or not isinstance(audit_finding.get("code"), str):
                continue
            severity = (
                "CRITICAL"
                if audit_finding.get("severity") == "error" or audit_finding["code"] in CRITICAL_AUDIT_CODES
                else "WARNING"
            )
            add_finding(audit_finding["code"], severity, "audit")

    signals_by_id = {
        str(signal.get("signal_id", f"signal-{index}")): signal
        for index, signal in enumerate(signals)
        if isinstance(signal, dict)
    }
    security_result = security_tool.audit_boundary({"qualified_snapshot": snapshot}, signals_by_id)
    security_has_findings = bool(security_result["findings"])
    for security_finding in security_result["findings"]:
        code = security_finding.get("code") if isinstance(security_finding, dict) else None
        add_finding(
            code if isinstance(code, str) and STABLE_ID.fullmatch(code) else "security_finding",
            "CRITICAL",
            "security",
        )

    audit_critical = any(
        isinstance(finding, dict)
        and (
            finding.get("severity") == "error"
            or finding.get("code") in CRITICAL_AUDIT_CODES
        )
        for finding in audit_result.get("findings", [])
    )
    critical = guard_blocked or audit_critical or security_has_findings or any(
        finding["code"] == "schema_major_mismatch" for finding in findings
    )
    noncritical = bool(findings)
    status = "BLOCKED" if critical else ("READY_WITH_FINDINGS" if noncritical else "READY")
    issue_candidates = _issue_candidates(manifest, repositories, audit_result, status, status_has_findings)
    observe_status = "PASSED" if all(record["drift"] == "CLEAN" for record in repositories) else "FINDINGS"
    guard_status = "BLOCKED" if guard_blocked else "PASSED"
    status_step = "FINDINGS" if status_has_findings else "PASSED"
    audit_step = "FINDINGS" if audit_has_findings else "PASSED"
    security_step = "BLOCKED" if security_has_findings else "PASSED"
    finding_codes = sorted({item["code"] for item in findings})
    ordered_steps = [
        _step("validate_parent_configuration", "PASSED"),
        _step(
            "observe_remote_heads",
            observe_status,
            False,
            [item["code"] for item in findings if item["source"] == "repository"],
        ),
        _step("guard_pinned_workspaces", guard_status, guard_blocked, guard_codes),
        _step("select_qualified_snapshot", "PASSED"),
        _step("materialize_snapshot", "PASSED"),
        _step("collect_status", status_step, False, ["audit_finding"] if status_has_findings else []),
        _step("run_audit", audit_step, False, ["audit_finding"] if audit_has_findings else []),
        _step(
            "run_security",
            security_step,
            security_has_findings,
            [item["code"] for item in findings if item["source"] == "security"],
        ),
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
        "workspace_guard": {
            "status": guard_status,
            "checked_repositories": sorted(repository["id"] for repository in guard["repositories"]),
            "finding_codes": guard_codes,
        },
        "findings": sorted(findings, key=lambda item: (item["code"], item["source"])),
        "issue_candidates": issue_candidates,
        "capabilities": _capabilities(status, findings),
        "remediation": [
            "review remote_update_candidate before changing a manifest pin" if "remote_update_candidate" in finding_codes else None,
            "retry remote observation before claiming the remote head is current" if "remote_observation_unavailable" in finding_codes else None,
            "resolve the pinned workspace guard manually; startup will not checkout, reset, or push" if guard_blocked else None,
            "review audit findings before enabling external create-only capabilities" if audit_has_findings else None,
            "stop affected capabilities and resolve the security boundary finding" if security_has_findings else None,
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
    parser.add_argument("--workspace-root", type=Path)
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
            resolve_path(args.workspace_root) if args.workspace_root else None,
        )
        result = _write_or_check(report, resolve_path(args.output), args.check)
    except (OSError, StartupError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
