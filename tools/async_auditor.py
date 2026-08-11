#!/usr/bin/env python3
"""Build a non-blocking asynchronous audit/refactoring proposal lane."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]

try:
    from tools.validate import load_yaml, validate_async_audit
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(ROOT))
    from tools.validate import load_yaml, validate_async_audit


class AsyncAuditorError(ValueError):
    """An asynchronous audit input or proposal is unsafe."""


LANE = "ASYNC_AUDIT"
QUALITY_GATE_STATUSES = {"NOT_RUN", "PASSED", "FAILED", "BLOCKED"}
FORBIDDEN_KEYS = {
    "conversation",
    "transcript",
    "prompt",
    "message",
    "raw_text",
    "raw_conversation",
    "user_text",
    "assistant_text",
    "body",
    "content",
    "PRIVATE_RAW",
    "RESTRICTED",
    "credential",
    "direct_identifier",
}
SHA40 = 40
SHA64 = 64


def _error(detail: str, remediation: str) -> AsyncAuditorError:
    return AsyncAuditorError(f"async auditor: {detail}; remediation: {remediation}")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise _error("timestamp must be a string", "use an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error(f"invalid timestamp {value!r}", "repair the source timestamp") from exc
    if parsed.tzinfo is None:
        raise _error("timestamp must include timezone", "include Z or an explicit UTC offset")
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _timestamp(value: object) -> str:
    return _parse_timestamp(value).isoformat().replace("+00:00", "Z")


def _scan_forbidden(value: object, path: str = "$") -> None:
    forbidden = {item.lower() for item in FORBIDDEN_KEYS}
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                raise _error(
                    f"{path}.{key} contains a forbidden raw or sensitive field",
                    "pass metadata-only audit findings and opaque artifact references",
                )
            _scan_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_forbidden(child, f"{path}[{index}]")


def _require_hash(value: object, length: int, field: str) -> str:
    if not isinstance(value, str) or len(value) != length or any(char not in "0123456789abcdef" for char in value):
        raise _error(f"{field} must be a lowercase SHA-{length * 4} hash", f"record the immutable {field}")
    return value


def _source_snapshot(snapshot: Mapping[str, object], parent_commit: str | None) -> tuple[dict, dict[str, str]]:
    if not isinstance(snapshot, Mapping):
        raise _error("source snapshot must be an object", "load data/snapshot.json from a qualified workspace")
    snapshot_hash = _require_hash(snapshot.get("snapshot_hash"), SHA64, "snapshot_hash")
    captured_at = _timestamp(snapshot.get("captured_at"))
    parent = parent_commit or snapshot.get("parent_commit")
    if not isinstance(parent, str) or len(parent) != SHA40 or any(char not in "0123456789abcdef" for char in parent):
        raise _error("parent commit is missing or invalid", "supply the current parent repository commit")
    repositories = snapshot.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise _error("source snapshot.repositories must be non-empty", "regenerate a qualified repository snapshot")
    result: list[dict] = []
    commits: dict[str, str] = {"agentic-art-orchestration": parent}
    seen: set[str] = set()
    for index, repository in enumerate(repositories):
        if not isinstance(repository, Mapping):
            raise _error(f"source snapshot repository {index} is not an object", "regenerate snapshot metadata")
        repository_id = repository.get("id")
        commit = repository.get("head") or repository.get("manifest_observed_commit")
        if not isinstance(repository_id, str) or not repository_id:
            raise _error(f"source snapshot repository {index} has no ID", "retain manifest repository IDs")
        if repository_id in seen or repository_id == "agentic-art-orchestration":
            raise _error(f"source snapshot repository {repository_id!r} is duplicated or reserved", "record each source repository once")
        if not isinstance(commit, str) or len(commit) != SHA40 or any(char not in "0123456789abcdef" for char in commit):
            raise _error(f"source snapshot commit for {repository_id!r} is invalid", "use the observed immutable 40-character commit")
        if repository.get("dirty") is True or repository.get("detached") is True or repository.get("ahead") not in (None, 0) or repository.get("behind") not in (None, 0):
            raise _error(
                f"source snapshot for {repository_id!r} is not qualified",
                "run workspace guard and create a clean, non-diverged snapshot before auditing",
            )
        seen.add(repository_id)
        commits[repository_id] = commit
        result.append({"repository": repository_id, "source_commit": commit})
    return {
        "snapshot_hash": snapshot_hash,
        "captured_at": captured_at,
        "parent_commit": parent,
        "repositories": sorted(result, key=lambda item: item["repository"]),
    }, commits


def _lease(lease: Mapping[str, object]) -> dict:
    if not isinstance(lease, Mapping):
        raise _error("audit lease must be an object", "acquire a lease on the ASYNC_AUDIT lane")
    if lease.get("lane", LANE) != LANE:
        raise _error("audit lease is not on the independent ASYNC_AUDIT lane", "use a separate audit queue and lease")
    if lease.get("status") != "held":
        raise _error("audit lease must be held", "acquire the audit lease before producing proposals")
    owner = lease.get("owner")
    execution_id = lease.get("execution_id")
    if not isinstance(owner, str) or not owner or owner == "unassigned":
        raise _error("audit lease owner is missing", "record the asynchronous worker owner")
    if not isinstance(execution_id, str) or not execution_id:
        raise _error("audit lease execution_id is missing", "record a resumable audit execution ID")
    expires_at = _timestamp(lease.get("expires_at"))
    return {
        "lane": LANE,
        "status": "held",
        "owner": owner,
        "execution_id": execution_id,
        "expires_at": expires_at,
    }


def _gate_record(repository: str, commit: str, value: object) -> dict:
    if value is None:
        value = {"status": "NOT_RUN"}
    if isinstance(value, str):
        value = {"status": value}
    if not isinstance(value, Mapping):
        raise _error(f"quality gate for {repository!r} must be metadata", "pass status and optional command only")
    status = value.get("status", "NOT_RUN")
    if status not in QUALITY_GATE_STATUSES:
        raise _error(f"quality gate for {repository!r} has unknown status {status!r}", "use NOT_RUN, PASSED, FAILED, or BLOCKED")
    observed = value.get("observed_commit", commit)
    if observed != commit:
        raise _error(f"quality gate for {repository!r} is for a different commit", "rerun the gate against the audited source commit")
    result = {
        "repository": repository,
        "status": status,
        "required": True,
        "observed_commit": commit,
    }
    command = value.get("command")
    if command is not None:
        if not isinstance(command, str) or not command:
            raise _error(f"quality gate command for {repository!r} is invalid", "record a metadata-only manifest command")
        result["command"] = command
    return result


def _scopes(repository_scopes: Mapping[str, object] | None, repositories: Mapping[str, str]) -> dict[str, list[str]]:
    scopes: dict[str, list[str]] = {repository: ["docs"] for repository in repositories}
    scopes["agentic-art-orchestration"] = ["docs", "execution", "schemas", "tools"]
    for repository, value in (repository_scopes or {}).items():
        if not isinstance(repository, str) or repository not in repositories:
            raise _error(f"scope names unknown repository {repository!r}", "use manifest repository IDs")
        if not isinstance(value, list) or not value or any(
            not isinstance(path, str)
            or not path
            or path.replace(chr(92), "/").startswith("/")
            or any(part in {"", ".", ".."} for part in path.replace(chr(92), "/").split("/"))
            for path in value
        ):
            raise _error(f"write scope for {repository!r} is unsafe", "use non-empty safe relative paths from knowledge_profile.write_scope")
        scopes[repository] = sorted(set(value))
    return scopes


def build_async_audit(
    audit_report: Mapping[str, object],
    snapshot: Mapping[str, object],
    lease: Mapping[str, object],
    quality_gates: Mapping[str, object] | None = None,
    repository_scopes: Mapping[str, object] | None = None,
    user_artifacts: list[Mapping[str, object]] | None = None,
    run_id: str = "AUDITOR-002:attempt-1",
    parent_commit: str | None = None,
) -> dict:
    """Create an idempotent audit result and gated repair proposals.

    The function only reads audit metadata and opaque artifact references. It
    never returns artifact content or an update/delete operation.
    """
    _scan_forbidden(audit_report)
    _scan_forbidden(snapshot)
    _scan_forbidden(lease)
    _scan_forbidden(quality_gates or {})
    _scan_forbidden(repository_scopes or {})
    _scan_forbidden(user_artifacts or [])
    if not isinstance(run_id, str) or not run_id or any(char.isspace() for char in run_id):
        raise _error("run_id must be a stable non-whitespace identifier", "reuse the checkpointed audit execution ID")
    if not isinstance(audit_report, Mapping):
        raise _error("audit report must be an object", "run the read-only parent audit first")
    if audit_report.get("blocking") is not False:
        raise _error("audit report must remain non-blocking", "record findings as asynchronous repair proposals")
    findings = audit_report.get("findings", [])
    if not isinstance(findings, list):
        raise _error("audit findings must be a list", "load a valid audit report")
    declared_finding_count = audit_report.get("finding_count")
    if declared_finding_count is None and isinstance(audit_report.get("summary"), Mapping):
        declared_finding_count = audit_report["summary"].get("finding_count")
    if declared_finding_count is not None and declared_finding_count != len(findings):
        raise _error("audit finding_count does not match findings", "regenerate the deterministic audit report")
    source_snapshot, commits = _source_snapshot(snapshot, parent_commit)
    audit_lease = _lease(lease)
    if _parse_timestamp(audit_lease["expires_at"]) <= _parse_timestamp(source_snapshot["captured_at"]):
        raise _error(
            "audit lease expired before the source snapshot was captured",
            "acquire a new audit lease and resume from its checkpoint",
        )
    scopes = _scopes(repository_scopes, commits)
    gates_input = quality_gates or {}
    gate_records: dict[str, dict] = {
        repository: _gate_record(repository, commit, gates_input.get(repository))
        for repository, commit in sorted(commits.items())
    }
    generated_candidates: list[tuple[str, dict]] = []
    for index, finding in enumerate(findings):
        if not isinstance(finding, Mapping):
            raise _error(f"audit finding {index} must be an object", "retain metadata-only audit findings")
        code = finding.get("code")
        subject = finding.get("subject")
        if not isinstance(code, str) or not code or not isinstance(subject, str) or not subject:
            raise _error(f"audit finding {index} lacks stable code or subject", "record a stable finding identity")
        finding_id = f"{code}:{subject}"
        if "observed" not in finding:
            raise _error(f"audit finding {finding_id!r} lacks observed evidence", "retain the audit finding evidence in the audit source")
        repository = finding.get("repository")
        if not isinstance(repository, str) or repository not in commits:
            repository = subject if subject in commits else "agentic-art-orchestration"
        gate = gate_records[repository]
        gate_status = gate["status"]
        if gate_status == "PASSED":
            kind = "DRAFT_PR"
            status = "READY"
            delivery_type = "DRAFT_PR_PLAN"
        elif gate_status in {"FAILED", "BLOCKED"}:
            kind = "ISSUE"
            status = "BLOCKED"
            delivery_type = "ISSUE_CANDIDATE"
        else:
            kind = "ISSUE"
            status = "TRIAGE"
            delivery_type = "ISSUE_CANDIDATE"
        deduplication_key = f"audit:{_hash({'code': code, 'subject': subject, 'repository': repository})[:32]}"
        candidate = {
            "kind": kind,
            "status": status,
            "repository": repository,
            "source_commit": commits[repository],
            "quality_gate_status": gate_status,
            "finding": {"code": code, "subject": subject, "audit_hash": _hash(audit_report)},
            "deduplication_key": deduplication_key,
            "privacy_safe_summary": f"Asynchronous audit found {code} for {subject}; review the owning repository boundary.",
            "acceptance": [
                f"Resolve audit finding {code} for {subject} at the owning repository boundary.",
                "Run the declared quality gate against the audited source commit.",
            ],
            "allowed_paths": scopes[repository],
            "human_gate": True,
            "delivery": {"type": delivery_type, "side_effect": "NONE"},
            "artifact_operations": [],
        }
        generated_candidates.append((deduplication_key, candidate))

    unique_candidates: dict[str, dict] = {}
    for key, candidate in generated_candidates:
        unique_candidates.setdefault(key, candidate)
    proposals: list[dict] = []
    for index, key in enumerate(sorted(unique_candidates), start=1):
        proposal = copy.deepcopy(unique_candidates[key])
        proposal["proposal_id"] = f"{run_id}:proposal:{index:03d}"
        proposals.append(proposal)
    finding_ids = sorted({f"{finding.get('code')}:{finding.get('subject')}" for finding in findings if isinstance(finding, Mapping)})
    audit_hash = _hash(audit_report)
    result = {
        "contract_version": "async-audit/v1",
        "run_id": run_id,
        "lane": LANE,
        "generated_at": source_snapshot["captured_at"],
        "interaction_blocking": False,
        "user_artifact_policy": "READ_ONLY",
        "source_snapshot": source_snapshot,
        "audit_observation": {
            "audit_hash": audit_hash,
            "status": "CLEAN" if not findings else "FINDINGS",
            "blocking": False,
            "finding_count": len(findings),
            "finding_ids": finding_ids,
        },
        "lease": audit_lease,
        "quality_gates": [gate_records[repository] for repository in sorted(gate_records)],
        "proposals": proposals,
        "artifact_operations": [],
    }
    errors = validate_async_audit(result, "async-auditor result")
    if errors:
        raise AsyncAuditorError("\n".join(errors))
    return result


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise _error(f"cannot observe parent commit: {exc}", "run the auditor inside the parent Git repository") from exc
    commit = result.stdout.strip()
    if len(commit) != SHA40 or any(char not in "0123456789abcdef" for char in commit):
        raise _error("parent Git HEAD is not a complete commit", "record a complete immutable parent commit")
    return commit


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _manifest_scopes() -> dict[str, list[str]]:
    manifest = load_yaml(ROOT / "config/repositories.yaml")
    scopes: dict[str, list[str]] = {}
    for repository in manifest.get("repositories", []) if isinstance(manifest, Mapping) else []:
        if not isinstance(repository, Mapping):
            continue
        profile = repository.get("knowledge_profile", {})
        write_scope = profile.get("write_scope", {}) if isinstance(profile, Mapping) else {}
        paths = write_scope.get("allowed_paths") if isinstance(write_scope, Mapping) else None
        if isinstance(paths, list):
            scopes[str(repository.get("id"))] = list(paths)
    return scopes


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a non-blocking asynchronous audit/refactoring plan")
    parser.add_argument("--audit", type=Path, default=ROOT / "data/audit.json")
    parser.add_argument("--snapshot", type=Path, default=ROOT / "data/snapshot.json")
    parser.add_argument("--state", type=Path, default=ROOT / "execution/state.yaml")
    parser.add_argument("--quality-gates", type=Path, default=None, help="metadata-only JSON map of repository gate results")
    parser.add_argument("--run-id", default="AUDITOR-002:attempt-1")
    parser.add_argument("--output", type=Path, default=ROOT / "data/async-audit.json")
    parser.add_argument("--check", action="store_true", help="verify an existing deterministic output without writing")
    args = parser.parse_args()
    try:
        with args.audit.open(encoding="utf-8") as handle:
            audit_report = json.load(handle)
        with args.snapshot.open(encoding="utf-8") as handle:
            snapshot = json.load(handle)
        state = load_yaml(args.state)
        gates = {}
        if args.quality_gates is not None:
            with args.quality_gates.open(encoding="utf-8") as handle:
                gates = json.load(handle)
        lease = dict(state.get("lease", {}))
        lease["lane"] = LANE
        lease.setdefault("execution_id", f"{args.run_id}:execution")
        result = build_async_audit(
            audit_report,
            snapshot,
            lease,
            quality_gates=gates,
            repository_scopes=_manifest_scopes(),
            run_id=args.run_id,
            parent_commit=_git_head(),
        )
        content = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        output_path = args.output.resolve()
        if args.check:
            if not output_path.is_file():
                raise _error("async audit output is missing", "run the auditor without --check to materialize the output")
            if output_path.read_text(encoding="utf-8") != content:
                raise _error("async audit output is stale", "rerun the auditor without --check")
        else:
            _write_atomic(output_path, content)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "command": "async-audit",
                "changed": not args.check,
                "proposal_count": len(result["proposals"]),
                "status": result["audit_observation"]["status"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
