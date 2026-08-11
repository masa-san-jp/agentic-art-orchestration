#!/usr/bin/env python3
"""Progress metadata-only Issue candidates through resumable improvement checkpoints."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
PARENT_REPOSITORY = "agentic-art-orchestration"
EXECUTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
STABLE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._:-][a-z0-9]+)*$")
STATUSES = {"NOT_STARTED", "PASSED", "FAILED", "BLOCKED"}
TEST_STATUSES = {"NOT_RUN", "PASSED", "FAILED"}
GATE_STATUSES = {"NOT_RUN", "PASSED", "FAILED", "BLOCKED"}
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

try:
    from tools.runtime import acquire_lease, save_checkpoint
    from tools.scheduler import schedule
    from tools.validate import (
        load_yaml,
        validate_improvement_loop,
        validate_issue_routing,
        validate_work_item,
    )
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(ROOT))
    from tools.runtime import acquire_lease, save_checkpoint
    from tools.scheduler import schedule
    from tools.validate import (
        load_yaml,
        validate_improvement_loop,
        validate_issue_routing,
        validate_work_item,
    )


class ImprovementLoopError(ValueError):
    """An Issue candidate or execution checkpoint cannot be progressed safely."""


def _error(detail: str, remediation: str) -> ImprovementLoopError:
    return ImprovementLoopError(f"improvement loop: {detail}; remediation: {remediation}")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _scan_forbidden(value: object, path: str = "$") -> None:
    forbidden = {item.lower() for item in FORBIDDEN_KEYS}
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                raise _error(
                    f"{path}.{key} contains a forbidden raw or sensitive field",
                    "pass privacy-safe Issue metadata and opaque references only",
                )
            _scan_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_forbidden(child, f"{path}[{index}]")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise _error("generated_at must be a timestamp", "reuse the routing result timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error(f"invalid timestamp {value!r}", "use an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise _error("timestamp must include timezone", "include Z or an explicit UTC offset")
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _manifest_index(manifest: Mapping[str, object]) -> dict[str, dict]:
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list):
        raise _error("manifest.repositories must be a list", "load config/repositories.yaml")
    result: dict[str, dict] = {}
    for repository in repositories:
        if not isinstance(repository, dict) or not isinstance(repository.get("id"), str):
            raise _error("manifest repository lacks an ID", "repair config/repositories.yaml")
        result[repository["id"]] = repository
    return result


def _parent_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise _error(f"cannot observe parent commit: {exc}", "run the improvement loop inside the parent repository") from exc
    commit = completed.stdout.strip()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise _error("parent HEAD is not a complete lowercase commit", "record an immutable parent source commit")
    return commit


def _safe_path(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")):
        return False
    parts = value.replace("\\", "/").split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _scope_for(repository_id: str, repository: Mapping[str, object] | None) -> list[str]:
    if repository_id == PARENT_REPOSITORY:
        return ["config", "docs", "execution", "schemas", "tests", "tools"]
    profile = repository.get("knowledge_profile", {}) if isinstance(repository, Mapping) else {}
    write_scope = profile.get("write_scope", {}) if isinstance(profile, Mapping) else {}
    paths = write_scope.get("allowed_paths") if isinstance(write_scope, Mapping) else None
    if not isinstance(paths, list) or not paths:
        raise _error(f"repository {repository_id!r} has no write scope", "read the manifest knowledge profile before implementation")
    if any(not _safe_path(path) for path in paths):
        raise _error(f"repository {repository_id!r} has an unsafe write scope", "use safe relative knowledge profile paths")
    return sorted(set(paths))


def _within_scope(path: str, scope: list[str]) -> bool:
    return _safe_path(path) and any(path == root or path.startswith(f"{root}/") for root in scope)


def _execution_record(record: Mapping[str, object], issue_key: str, base_commit: str, scope: list[str]) -> dict:
    _scan_forbidden(record)
    if record.get("issue_key") != issue_key:
        raise _error(f"execution evidence is for the wrong Issue {record.get('issue_key')!r}", "key execution evidence by the canonical Issue key")
    if record.get("base_commit", base_commit) != base_commit:
        raise _error(f"execution evidence for {issue_key!r} uses a different base commit", "rerun the worker from the immutable source commit")
    implementation = record.get("implementation_status", "NOT_STARTED")
    test_status = record.get("test_status", "NOT_RUN")
    gate_status = record.get("quality_gate_status", "NOT_RUN")
    if implementation not in STATUSES:
        raise _error(f"implementation status for {issue_key!r} is invalid", "use NOT_STARTED, PASSED, FAILED, or BLOCKED")
    if test_status not in TEST_STATUSES:
        raise _error(f"test status for {issue_key!r} is invalid", "use NOT_RUN, PASSED, or FAILED")
    if gate_status not in GATE_STATUSES:
        raise _error(f"quality gate status for {issue_key!r} is invalid", "use NOT_RUN, PASSED, FAILED, or BLOCKED")
    changed_paths = record.get("changed_paths", [])
    test_refs = record.get("test_refs", [])
    if not isinstance(changed_paths, list) or len(changed_paths) != len(set(changed_paths)) or any(not _within_scope(path, scope) for path in changed_paths):
        raise _error(f"execution evidence for {issue_key!r} has an unsafe or out-of-scope path", "keep implementation paths within the manifest write scope")
    if not isinstance(test_refs, list) or any(not isinstance(reference, str) or not STABLE_ID_PATTERN.fullmatch(reference) for reference in test_refs):
        raise _error(f"test references for {issue_key!r} are invalid", "record stable test evidence IDs without raw command output")
    observed_gate_commit = record.get("quality_gate_commit", base_commit)
    if observed_gate_commit != base_commit:
        raise _error(f"quality gate evidence for {issue_key!r} uses a different commit", "run the declared gate against the worker base commit")
    return {
        "implementation_status": implementation,
        "test_status": test_status,
        "quality_gate_status": gate_status,
        "changed_paths": sorted(changed_paths),
        "test_refs": sorted(set(test_refs)),
    }


def _build_work_item(
    issue_key: str,
    summary_code: str,
    target: str,
    repository: Mapping[str, object] | None,
    base_commit: str,
    allowed_paths: list[str],
    ordinal: int,
    generated_at: str,
) -> dict:
    work_item_id = f"IMPROVEMENT-WORK-{ordinal:03d}"
    quality_gates = list(repository.get("quality_gates", [])) if isinstance(repository, Mapping) else [".venv/bin/python tools/validate.py --check"]
    instructions = repository.get("instructions", "AGENTS.md") if isinstance(repository, Mapping) else "AGENTS.md"
    contracts = []
    if isinstance(repository, Mapping):
        contract = repository.get("export_contract") or repository.get("import_contract")
        if isinstance(contract, str):
            contracts.append(contract)
    return {
        "version": 1,
        "id": work_item_id,
        "title": "Implement metadata-only improvement candidate",
        "owner_repository": target,
        "target_repositories": [target],
        "allowed_paths": allowed_paths,
        "depends_on": [],
        "context": {
            "required_files": ["AGENTS.md", instructions],
            "contracts": contracts,
            "source_commits": {target: base_commit},
        },
        "acceptance": [
            {
                "id": "issue-acceptance",
                "description": f"Resolve {summary_code} at the authoritative repository boundary.",
                "observable": "implementation, tests, and the declared quality gate are recorded",
            },
            {
                "id": "human-gate",
                "description": "Prepare a draft PR plan without merging or releasing.",
                "observable": "remote operations remain empty and human_gate is true",
            },
        ],
        "checks": [
            {"repository": target, "command": command, "required": True}
            for command in quality_gates
        ],
        "risk": {
            "level": "medium",
            "data_boundary": "derived-only",
            "mitigations": ["preserve source commit and write scope", "keep remote operations empty", "retain human merge and release gates"],
        },
        "attempts": {"used": 0, "max": 3},
        "lease": {
            "status": "available",
            "owner": "unassigned",
            "expires_at": _timestamp(_parse_timestamp(generated_at) + timedelta(minutes=45)),
        },
        "checkpoint": {
            "start_point": base_commit,
            "next_action": "select the next checkpoint",
            "last_result": "not_started",
        },
        "terminal_criteria": ["implementation, tests, and quality gate pass", "human-gated draft PR plan is prepared"],
        "terminal_state": "READY",
        "evidence": {"commits": [], "pull_requests": [], "tests": [], "changed_paths": []},
    }


def _checkpoint(run_id: str, issue_key: str, step: str, status: str, evidence_refs: list[str] | None = None) -> dict:
    return {
        "step": step,
        "status": status,
        "idempotency_key": f"{run_id}:issue:{_hash(issue_key)[:12]}:{step.lower()}",
        "evidence_refs": sorted(set(evidence_refs or [])),
    }


def build_improvement_loop(
    routing_result: Mapping[str, object],
    execution_evidence: list[Mapping[str, object]] | None = None,
    manifest: Mapping[str, object] | None = None,
    run_id: str = "IMPROVEMENT-001:attempt-1",
    parent_commit: str | None = None,
) -> dict:
    """Select routed Issues and progress observed worker evidence to a human-gated draft plan."""
    if not isinstance(run_id, str) or not run_id or EXECUTION_ID_PATTERN.fullmatch(run_id) is None:
        raise _error("run_id is invalid", "reuse a stable improvement execution ID")
    loaded_manifest = deepcopy(dict(manifest)) if manifest is not None else load_yaml(ROOT / "config/repositories.yaml")
    repositories = _manifest_index(loaded_manifest)
    routing_copy = deepcopy(dict(routing_result))
    routing_errors = validate_issue_routing(routing_copy, "improvement routing input")
    if routing_errors:
        raise ImprovementLoopError("\n".join(routing_errors))
    _scan_forbidden(execution_evidence or [])
    records_by_key: dict[str, Mapping[str, object]] = {}
    for record in execution_evidence or []:
        if not isinstance(record, Mapping) or not isinstance(record.get("issue_key"), str):
            raise _error("execution evidence must have a stable issue_key", "key each worker checkpoint by the canonical Issue")
        key = record["issue_key"]
        if key in records_by_key:
            raise _error(f"execution evidence duplicates Issue {key!r}", "retain one resumable evidence record per Issue")
        records_by_key[key] = deepcopy(dict(record))

    routes = [route for route in routing_copy.get("routes", []) if isinstance(route, Mapping)]
    candidates: dict[str, Mapping[str, object]] = {}
    candidate_routes: dict[str, Mapping[str, object]] = {}
    for route in sorted(routes, key=lambda item: str(item.get("feedback_id", ""))):
        candidate = route.get("issue_candidate")
        if not isinstance(candidate, Mapping):
            continue
        key = candidate.get("issue_key")
        if not isinstance(key, str) or not STABLE_ID_PATTERN.fullmatch(key):
            raise _error("routing candidate has no stable Issue key", "route only validated metadata-only candidates")
        if key in candidates:
            continue
        candidates[key] = deepcopy(dict(candidate))
        candidate_routes[key] = route
    unknown_records = sorted(set(records_by_key) - set(candidates))
    if unknown_records:
        raise _error(f"execution evidence names unknown Issues {unknown_records!r}", "do not execute work outside the routed Issue set")

    generated_at = routing_copy.get("generated_at")
    _parse_timestamp(generated_at)
    parent = parent_commit or _parent_commit()
    input_issue_keys = sorted(candidates)
    outcomes: list[dict] = []
    plans: list[dict] = []
    duplicate_suppressions: list[dict] = []
    seen_issue_keys: set[str] = set()

    for ordinal, issue_key in enumerate(input_issue_keys, start=1):
        candidate = candidates[issue_key]
        route = candidate_routes[issue_key]
        target = candidate.get("target_repository")
        repository = repositories.get(target) if isinstance(target, str) else None
        base_commit = None
        if target == PARENT_REPOSITORY:
            base_commit = parent
        elif repository is not None:
            base_commit = repository.get("observed_commit")
        source_feedback_ids = sorted(candidate.get("source_feedback_ids", []))
        summary_code = candidate["summary_code"]
        checkpoints: list[dict] = [_checkpoint(run_id, issue_key, "SELECT", "PASSED", [f"issue:{_hash(issue_key)[:12]}"])]
        work_item_output = None
        draft_plan = None
        implementation_status = "NOT_STARTED"
        test_status = "NOT_RUN"
        quality_gate_status = "NOT_RUN"
        changed_paths: list[str] = []
        delivery_status = "TRIAGE"
        reason = "Issue candidate requires triage before autonomous implementation."

        eligible = (
            route.get("routing_status") == "ROUTED"
            and candidate.get("creation_permitted") is True
            and candidate.get("human_gate") is True
            and candidate.get("side_effect") == "NONE"
            and isinstance(target, str)
            and target in (set(repositories) | {PARENT_REPOSITORY})
            and base_commit is not None
        )
        if eligible:
            scope = _scope_for(target, repository)
            record = records_by_key.get(issue_key)
            if record is None:
                work_item = _build_work_item(issue_key, summary_code, target, repository, base_commit, [scope[0]], ordinal, generated_at)
                validation_errors = validate_work_item(work_item, f"improvement work item {issue_key}")
                if validation_errors:
                    raise ImprovementLoopError("\n".join(validation_errors))
                scheduled = schedule([work_item])
                if scheduled["selected"] != [work_item["id"]]:
                    raise _error(f"scheduler excluded eligible Issue {issue_key!r}", "retain the exclusion reason and do not execute it")
                active = acquire_lease(work_item, "improvement-agent", generated_at, lease_minutes=45)
                active = save_checkpoint(active, "improvement-agent", "await worker implementation evidence", result="checkpointed", decision="preserve source commit and human gate")
                work_item_output = {
                    "work_item_id": work_item["id"],
                    "owner_repository": target,
                    "allowed_paths": [scope[0]],
                    "source_commit": base_commit,
                    "scheduler_status": "SELECTED",
                    "runtime_execution_id": active["checkpoint"]["execution_id"],
                    "terminal_state": active["terminal_state"],
                }
                checkpoints.extend([
                    _checkpoint(run_id, issue_key, "IMPLEMENT", "NOT_STARTED"),
                    _checkpoint(run_id, issue_key, "TEST", "NOT_STARTED"),
                    _checkpoint(run_id, issue_key, "QUALITY_GATE", "NOT_STARTED"),
                    _checkpoint(run_id, issue_key, "DRAFT_PR", "SKIPPED"),
                ])
                delivery_status = "WAITING"
                reason = "Eligible Issue is selected and checkpointed; await implementation/test/gate evidence."
            else:
                evidence = _execution_record(record, issue_key, base_commit, scope)
                implementation_status = evidence["implementation_status"]
                test_status = evidence["test_status"]
                quality_gate_status = evidence["quality_gate_status"]
                changed_paths = evidence["changed_paths"]
                implementation_checkpoint = "PASSED" if implementation_status == "PASSED" else ("FAILED" if implementation_status == "FAILED" else ("BLOCKED" if implementation_status == "BLOCKED" else "NOT_STARTED"))
                test_checkpoint = "PASSED" if test_status == "PASSED" else ("FAILED" if test_status == "FAILED" else "NOT_STARTED")
                gate_checkpoint = "PASSED" if quality_gate_status == "PASSED" else ("FAILED" if quality_gate_status == "FAILED" else ("BLOCKED" if quality_gate_status == "BLOCKED" else "NOT_STARTED"))
                all_passed = implementation_status == "PASSED" and test_status == "PASSED" and quality_gate_status == "PASSED" and bool(changed_paths) and bool(evidence["test_refs"])
                if all_passed:
                    delivery_status = "DRAFT_PR_READY"
                    reason = "Implementation, tests, and the declared quality gate passed; draft PR remains human-gated."
                elif "FAILED" in {implementation_status, test_status, quality_gate_status} or "BLOCKED" in {implementation_status, quality_gate_status}:
                    delivery_status = "BLOCKED"
                    reason = "A required implementation, test, or quality gate failed; do not prepare a draft PR."
                else:
                    delivery_status = "WAITING"
                    reason = "Execution evidence is incomplete; preserve the checkpoint and resume the missing step."
                work_item_paths = changed_paths or [scope[0]]
                work_item = _build_work_item(issue_key, summary_code, target, repository, base_commit, work_item_paths, ordinal, generated_at)
                validation_errors = validate_work_item(work_item, f"improvement work item {issue_key}")
                if validation_errors:
                    raise ImprovementLoopError("\n".join(validation_errors))
                scheduled = schedule([work_item])
                if scheduled["selected"] != [work_item["id"]]:
                    raise _error(f"scheduler excluded eligible Issue {issue_key!r}", "retain the exclusion reason and do not execute it")
                active = acquire_lease(work_item, "improvement-agent", generated_at, lease_minutes=45)
                checkpoint_result = "passed" if all_passed else ("failed" if delivery_status == "BLOCKED" else "checkpointed")
                active = save_checkpoint(active, "improvement-agent", "await human approval of draft PR plan" if all_passed else "resume the missing or failed improvement step", result=checkpoint_result, decision="preserve source commit and human gate")
                work_item_output = {
                    "work_item_id": work_item["id"],
                    "owner_repository": target,
                    "allowed_paths": work_item_paths,
                    "source_commit": base_commit,
                    "scheduler_status": "SELECTED",
                    "runtime_execution_id": active["checkpoint"]["execution_id"],
                    "terminal_state": active["terminal_state"],
                }
                checkpoints.extend([
                    _checkpoint(run_id, issue_key, "IMPLEMENT", implementation_checkpoint, [f"implementation:{_hash(issue_key)[:12]}"] if implementation_checkpoint == "PASSED" else []),
                    _checkpoint(run_id, issue_key, "TEST", test_checkpoint, evidence["test_refs"]),
                    _checkpoint(run_id, issue_key, "QUALITY_GATE", gate_checkpoint, [f"gate:{target}:passed"] if gate_checkpoint == "PASSED" else []),
                    _checkpoint(run_id, issue_key, "DRAFT_PR", "PASSED" if all_passed else "SKIPPED"),
                ])
                if all_passed:
                    draft_plan = {
                        "plan_id": f"draft:{_hash(issue_key)[:32]}",
                        "issue_key": issue_key,
                        "target_repository": target,
                        "base_commit": base_commit,
                        "branch_name": f"improvement/{target}/{_hash(issue_key)[:12]}",
                        "changed_paths": changed_paths,
                        "title_code": summary_code,
                        "quality_gate_status": "PASSED",
                        "human_gate": True,
                        "merge_permitted": False,
                        "release_permitted": False,
                        "side_effect": "NONE",
                    }
                    plans.append(draft_plan)
        else:
            checkpoints.extend([
                _checkpoint(run_id, issue_key, "IMPLEMENT", "SKIPPED"),
                _checkpoint(run_id, issue_key, "TEST", "SKIPPED"),
                _checkpoint(run_id, issue_key, "QUALITY_GATE", "SKIPPED"),
                _checkpoint(run_id, issue_key, "DRAFT_PR", "SKIPPED"),
            ])
            if route.get("routing_status") == "BLOCKED":
                delivery_status = "BLOCKED"
                reason = "Issue creation consent or authority boundary is blocked; no implementation is permitted."
            elif route.get("routing_status") == "DUPLICATE_SUPPRESSED":
                delivery_status = "DUPLICATE_SUPPRESSED"
                reason = "Duplicate Issue candidate is suppressed before scheduler or worker execution."
            else:
                delivery_status = "TRIAGE"
                reason = "Authority, confidence, or human consent requires triage before implementation."

        outcomes.append(
            {
                "issue_key": issue_key,
                "summary_code": summary_code,
                "target_repository": target,
                "source_feedback_ids": source_feedback_ids,
                "delivery_status": delivery_status,
                "implementation_status": implementation_status,
                "test_status": test_status,
                "quality_gate_status": quality_gate_status,
                "base_commit": base_commit,
                "changed_paths": changed_paths,
                "checkpoints": checkpoints,
                "reason": reason,
                "work_item": work_item_output,
                "draft_pr_plan": draft_plan,
            }
        )

    for suppression in routing_copy.get("duplicate_suppressions", []):
        if not isinstance(suppression, Mapping):
            continue
        issue_key = suppression.get("issue_key")
        canonical = suppression.get("issue_key")
        suppressed_feedback_id = suppression.get("suppressed_feedback_id")
        if isinstance(issue_key, str) and isinstance(canonical, str) and isinstance(suppressed_feedback_id, str):
            duplicate_suppressions.append(
                {
                    "issue_key": issue_key,
                    "canonical_issue_key": canonical,
                    "suppressed_feedback_ids": [suppressed_feedback_id],
                }
            )

    result = {
        "contract_version": "improvement-loop/v1",
        "run_id": run_id,
        "lane": "AUTONOMOUS_IMPROVEMENT",
        "generated_at": _timestamp(_parse_timestamp(generated_at)),
        "interaction_blocking": False,
        "user_artifact_policy": "READ_ONLY",
        "input_issue_keys": input_issue_keys,
        "outcomes": outcomes,
        "duplicate_suppressions": duplicate_suppressions,
        "draft_pr_plans": plans,
        "remote_operations": [],
    }
    errors = validate_improvement_loop(result, loaded_manifest, "improvement loop result")
    if errors:
        raise ImprovementLoopError("\n".join(errors))
    return result


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Progress routed Issues to human-gated draft PR plans")
    parser.add_argument("--routing", type=Path, default=ROOT / "data/feedback-routing.json")
    parser.add_argument("--execution", type=Path, default=ROOT / "tests/fixtures/improvement/execution.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/repositories.yaml")
    parser.add_argument("--run-id", default="IMPROVEMENT-001:attempt-1")
    parser.add_argument("--output", type=Path, default=ROOT / "data/improvement-loop.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        with args.routing.open(encoding="utf-8") as handle:
            routing = json.load(handle)
        with args.execution.open(encoding="utf-8") as handle:
            execution = json.load(handle)
        manifest = load_yaml(args.manifest)
        result = build_improvement_loop(routing, execution, manifest, args.run_id)
        content = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        output_path = args.output.resolve()
        if args.check:
            if not output_path.is_file():
                raise _error("improvement output is missing", "run without --check to materialize improvement-loop.json")
            if output_path.read_text(encoding="utf-8") != content:
                raise _error("improvement output is stale", "rerun the improvement loop without --check")
        else:
            _write_atomic(output_path, content)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "command": "improvement-loop",
                "changed": not args.check,
                "outcome_count": len(result["outcomes"]),
                "draft_pr_plan_count": len(result["draft_pr_plans"]),
                "remote_operation_count": len(result["remote_operations"]),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
