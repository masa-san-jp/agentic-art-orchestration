#!/usr/bin/env python3
"""Run a provider-neutral research worker with resumable, fail-closed state."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable

try:
    from tools.validate import _schema_errors, load_json, load_yaml
    from tools.output_destinations import (
        destinations_profile_selected,
        resolve_destinations,
        validate_destination_resolution,
        write_resolution_evidence,
    )
    from tools.repo_local_destinations import ENVIRONMENT as PROJECT_ROOT_ENV, resolve_project_root
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.validate import _schema_errors, load_json, load_yaml
    from tools.output_destinations import (
        destinations_profile_selected,
        resolve_destinations,
        validate_destination_resolution,
        write_resolution_evidence,
    )
    from tools.repo_local_destinations import ENVIRONMENT as PROJECT_ROOT_ENV, resolve_project_root


ROOT = Path(__file__).resolve().parents[1]
ACTION_SCHEMA = ROOT / "schemas/agent-action.schema.json"
RESULT_SCHEMA = ROOT / "schemas/agent-result.schema.json"
STATE_SCHEMA = ROOT / "schemas/autonomous-run.schema.json"
HUMAN_GATES_PATH = ROOT / "config/human-gates.yaml"
SHA40 = "^[0-9a-f]{40}$"
SHA64 = "^[0-9a-f]{64}$"
RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
HUMAN_OPERATIONS = (
    "merge",
    "release",
    "public_share",
    "consent_expansion",
    "destructive_git",
    "external_cost_over_declared_budget",
    "physical_action",
)
TERMINAL_STATUSES = {
    "RESEARCH_COMPLETE",
    "PLAN_READY",
    "BLOCKED_HUMAN",
    "BLOCKED_EXTERNAL",
    "FAILED_RETRY_EXHAUSTED",
}
SENSITIVE_KEYS = {
    "conversation",
    "conversation_body",
    "raw_conversation",
    "raw_response",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
    "api_key",
    "private_raw",
    "restricted",
    "direct_identifier",
    "free_text",
}
SENSITIVE_MARKERS = ("PRIVATE_RAW", "RESTRICTED", "BEGIN PRIVATE KEY")


class AutonomousRunnerError(ValueError):
    """A worker action, result, or supervisor transition is unsafe."""


def _error(detail: str, remediation: str) -> AutonomousRunnerError:
    return AutonomousRunnerError(f"autonomous-runner: {detail}; remediation: {remediation}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise _error("timestamp is invalid", "use an RFC 3339 timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise _error("timestamp has no timezone", "use Z or an explicit UTC offset")
    return parsed


def _digest(value: object) -> str:
    payload = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _contains_sensitive(value: object, path: str = "$") -> str | None:
    """Return only a field path, never the protected value itself."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in SENSITIVE_KEYS or any(marker.casefold() in normalized for marker in SENSITIVE_MARKERS):
                return f"{path}.{key}"
            found = _contains_sensitive(child, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _contains_sensitive(child, f"{path}[{index}]")
            if found:
                return found
    elif isinstance(value, str):
        upper = value.upper()
        if any(marker in upper for marker in SENSITIVE_MARKERS):
            return path
    return None


def _schema_errors_for(value: dict[str, Any], schema_path: Path, source: str) -> list[str]:
    try:
        schema = load_json(schema_path)
    except (OSError, ValueError) as exc:
        return [f"{source}: schema unavailable; remediation: restore {schema_path.name}: {exc}"]
    return [f"{source}: {item}; remediation: satisfy the closed worker contract" for item in _schema_errors(value, schema)]


def validate_agent_action(action: dict[str, Any], source: str = "agent-action") -> list[str]:
    errors = _schema_errors_for(action, ACTION_SCHEMA, source)
    if not isinstance(action, dict):
        return errors
    sensitive = _contains_sensitive(action)
    if sensitive:
        errors.append(f"{source}: sensitive field at {sensitive}; remediation: pass metadata-only action fields")
    if any(operation not in HUMAN_OPERATIONS for operation in action.get("requested_operations", [])):
        errors.append(f"{source}.requested_operations: unknown operation; remediation: use the configured finite operation vocabulary")
    forbidden = action.get("forbidden_operations")
    if isinstance(forbidden, list) and not set(HUMAN_OPERATIONS).issubset(forbidden):
        errors.append(f"{source}.forbidden_operations: human gate set is incomplete; remediation: include every configured human operation")
    return errors


def validate_agent_result(result: dict[str, Any], source: str = "agent-result") -> list[str]:
    errors = _schema_errors_for(result, RESULT_SCHEMA, source)
    if not isinstance(result, dict):
        return errors
    sensitive = _contains_sensitive(result)
    if sensitive:
        errors.append(f"{source}: sensitive field at {sensitive}; remediation: return metadata-only result fields")
    status = result.get("status")
    blocker = result.get("blocker_category")
    operations = result.get("requested_operations", [])
    if isinstance(operations, list) and any(operation not in HUMAN_OPERATIONS for operation in operations):
        errors.append(f"{source}.requested_operations: unknown operation; remediation: use the configured finite operation vocabulary")
    checks = result.get("checks", [])
    if isinstance(checks, list):
        ids = [item.get("id") for item in checks if isinstance(item, dict)]
        if len(ids) != len(set(ids)):
            errors.append(f"{source}.checks: duplicate check id; remediation: report each check once")
    if status == "COMPLETED":
        if blocker != "none":
            errors.append(f"{source}.blocker_category: completed result must use none; remediation: report a blocker or complete cleanly")
        if operations:
            errors.append(f"{source}.requested_operations: completed result cannot request an operation; remediation: stop before human-gated work")
        if not isinstance(result.get("commit_sha"), str):
            errors.append(f"{source}.commit_sha: completed result needs a commit SHA; remediation: return the immutable worker commit")
        if isinstance(checks, list) and any(item.get("status") != "PASSED" for item in checks if isinstance(item, dict)):
            errors.append(f"{source}.checks: completed result has a non-passing check; remediation: return COMPLETED only after all checks pass")
    elif status == "BLOCKED" and blocker == "none":
        errors.append(f"{source}.blocker_category: blocked result needs a category; remediation: classify human or external blocking")
    elif status == "FAILED" and blocker not in {"retryable", "worker_contract"}:
        errors.append(f"{source}.blocker_category: failed result needs retryable or worker_contract; remediation: classify the failure without executing it")
    return errors


def validate_autonomous_state(state: dict[str, Any], source: str = "autonomous-run") -> list[str]:
    errors = _schema_errors_for(state, STATE_SCHEMA, source)
    if not isinstance(state, dict):
        return errors
    if "destination_resolution" in state:
        errors.extend(validate_destination_resolution(state["destination_resolution"], f"{source}.destination_resolution"))
        if isinstance(state["destination_resolution"], dict) and state["destination_resolution"].get("run_id") != state.get("run_id"):
            errors.append(f"{source}.destination_resolution.run_id: must match run_id; remediation: resolve the same run")
    sensitive = _contains_sensitive(state)
    # The generated privacy booleans intentionally contain names such as
    # private_raw_stored; scan values and arbitrary fields, not that fixed map.
    if sensitive and not sensitive.startswith("$.privacy."):
        errors.append(f"{source}: sensitive field at {sensitive}; remediation: keep supervisor state metadata-only")
    status = state.get("status")
    if status == "PLAN_READY":
        errors.append(f"{source}.status: legacy worker-only PLAN_READY requires canonical Production revalidation; remediation: resume through the knowledge cycle")
    if status == "PLAN_READY" and state.get("stage") != "plan":
        errors.append(f"{source}.stage: PLAN_READY must be in plan stage; remediation: advance the stage atomically")
    if status != "PLAN_READY" and state.get("stage") == "plan":
        errors.append(f"{source}.stage: non-terminal research state cannot be in plan stage; remediation: preserve the research checkpoint")
    lease = state.get("lease", {})
    if lease.get("status") == "available" and lease.get("owner") != "unassigned":
        errors.append(f"{source}.lease: available lease must be unassigned; remediation: release the supervisor lease")
    if lease.get("status") == "held" and lease.get("owner") == "unassigned":
        errors.append(f"{source}.lease: held lease needs an owner; remediation: record the process owner")
    if status in TERMINAL_STATUSES and lease.get("status") == "held":
        errors.append(f"{source}.lease: terminal state cannot retain a held lease; remediation: release the lease atomically")
    return errors


def _human_gate_operations() -> set[str]:
    try:
        config = load_yaml(HUMAN_GATES_PATH)
    except (OSError, ValueError) as exc:
        raise _error("human gate policy is unavailable", "restore config/human-gates.yaml") from exc
    operations = config.get("human_operations") if isinstance(config, dict) else None
    if operations != list(HUMAN_OPERATIONS):
        raise _error("human gate policy is not the closed v1 policy", "restore the seven explicit human operations")
    if config.get("default_status") != "BLOCKED_HUMAN" or config.get("execution_policy") != "never_execute_requested_human_operation":
        raise _error("human gate policy weakens the execution boundary", "keep requested human operations blocked")
    return set(operations)


def _safe_run_id(run_id: str) -> str:
    import re

    if not isinstance(run_id, str) or re.fullmatch(RUN_ID_PATTERN, run_id) is None:
        raise _error("run_id is unsafe", "use letters, digits, dot, underscore, colon, or hyphen")
    return run_id


def _safe_relative_paths(paths: Iterable[str]) -> list[str]:
    result = list(paths)
    if not result or len(result) != len(set(result)):
        raise _error("allowed_paths must be non-empty and unique", "declare each relative worker path once")
    for path in result:
        parts = path.replace("\\", "/").split("/")
        if not path or path.startswith(("/", "\\")) or any(part in {"", ".", ".."} for part in parts):
            raise _error("allowed_paths contains an unsafe path", "use normalized repository-relative paths")
    return result


def _path_is_allowed(path: str, allowed_paths: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(normalized == allowed or normalized.startswith(f"{allowed}/") for allowed in allowed_paths)


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except FileExistsError as exc:
        raise _error("atomic temporary path already exists", "remove only the stale run-scoped temporary file") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error("worker response is not valid UTF-8 JSON", "return one closed agent-result object") from exc
    if not isinstance(value, dict):
        raise _error("worker response must be an object", "return one closed agent-result object")
    return value


def _atomic_request(run_dir: Path, action: dict[str, Any]) -> Path:
    path = run_dir / "agent-action.json"
    _atomic_write(path, action)
    return path


def _lease_lock(run_dir: Path, owner: str, expires_at: str, execution_id: str) -> Path:
    path = run_dir / "lease.lock"
    payload = json.dumps({"owner": owner, "expires_at": expires_at, "execution_id": execution_id}, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            expired = _parse_time(existing.get("expires_at")) <= _parse_time(_now())
        except (OSError, ValueError, json.JSONDecodeError):
            expired = False
        if not expired:
            raise _error("run already has an active lease", "wait for the recorded lease expiry before resuming")
        try:
            path.unlink()
        except OSError as exc:
            raise _error("expired run lease cannot be reclaimed", "remove the stale run-scoped lease after confirming no process is active") from exc
        return _lease_lock(run_dir, owner, expires_at, execution_id)
    return path


def _release_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _git_head() -> str:
    result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    commit = result.stdout.strip()
    import re

    if result.returncode != 0 or re.fullmatch(SHA40, commit) is None:
        raise _error("parent source commit is unavailable", "pass --source-commit from an immutable checkout")
    return commit


def _new_state(run_id: str, child_repository: str, source_commit: str, project_path: str, allowed_paths: list[str], now: str) -> dict[str, Any]:
    return {
        "contract_version": "autonomous-run/v1",
        "run_id": run_id,
        "status": "RESEARCH_PENDING",
        "stage": "research",
        "child_repository": child_repository,
        "source_commit": source_commit,
        "project_path": project_path,
        "allowed_paths": allowed_paths,
        "attempts": 0,
        "retry_counts": {},
        "accepted_result_digest": None,
        "checkpoint": {"status": "RESEARCH_PENDING", "next_action": "invoke the research worker", "last_result_digest": None},
        "lease": {"status": "available", "owner": "unassigned", "expires_at": now},
        "history": [],
        "privacy": {"raw_conversation_stored": False, "credentials_stored": False, "private_raw_stored": False, "restricted_stored": False},
    }


def _failure_fingerprint(stage: str, category: str, detail: str) -> str:
    # detail is already a sanitized code, never subprocess output.
    return _digest({"stage": stage, "category": category, "detail": detail})


def _make_action(state: dict[str, Any], attempt: int) -> dict[str, Any]:
    action = {
        "contract_version": "agent-action/v1",
        "run_id": state["run_id"],
        "stage": "research",
        "child_repository": state["child_repository"],
        "source_commit": state["source_commit"],
        "project_path": state["project_path"],
        "allowed_paths": state["allowed_paths"],
        "forbidden_operations": list(HUMAN_OPERATIONS),
        "completion_command": "return agent-result/v1 with all declared checks",
        "resume_command": "resume the same run_id from supervisor.json",
        "requested_operations": [],
        "attempt": attempt,
    }
    errors = validate_agent_action(action)
    if errors:
        raise _error("generated action is invalid", errors[0])
    return action


def _set_released(state: dict[str, Any], status: str, checkpoint_status: str, next_action: str, result_digest: str | None = None) -> None:
    state["status"] = status
    state["checkpoint"] = {"status": checkpoint_status, "next_action": next_action, "last_result_digest": result_digest}
    state["lease"]["status"] = "available"
    state["lease"]["owner"] = "unassigned"


def _record_result(state: dict[str, Any], result: dict[str, Any], result_digest: str, error_fingerprint: str | None = None) -> None:
    status = result.get("status")
    state["history"].append({
        "attempt": state["attempts"],
        "stage": "research",
        "outcome": status,
        "result_digest": result_digest,
        "error_fingerprint": error_fingerprint,
    })


def _apply_result(state: dict[str, Any], result: dict[str, Any], result_digest: str) -> None:
    gate_operations = _human_gate_operations()
    requested = set(result.get("requested_operations", []))
    if requested & gate_operations or result.get("blocker_category") == "human":
        _record_result(state, result, result_digest)
        _set_released(state, "BLOCKED_HUMAN", "BLOCKED_HUMAN", "record human decision for the requested operation", result_digest)
        return
    if result.get("status") == "COMPLETED":
        if not all(_path_is_allowed(path, state["allowed_paths"]) for path in result.get("changed_paths", [])):
            _record_result(state, result, result_digest)
            _set_released(state, "BLOCKED_EXTERNAL", "BLOCKED_EXTERNAL", "inspect the worker changed-path boundary", result_digest)
            return
        _record_result(state, result, result_digest)
        state["accepted_result_digest"] = result_digest
        _set_released(state, "RESEARCH_COMPLETE", "RESEARCH_COMPLETE",
                      "resume the same run through the canonical Research handoff, Production builder and knowledge-cycle completion verifier", result_digest)
        return
    if result.get("status") == "BLOCKED":
        _record_result(state, result, result_digest)
        _set_released(state, "BLOCKED_EXTERNAL", "BLOCKED_EXTERNAL", "resolve the external blocker before resuming", result_digest)
        return
    fingerprint = result.get("error_fingerprint") or _failure_fingerprint("research", result.get("blocker_category", "worker_contract"), "worker_failed")
    count = state["retry_counts"].get(fingerprint, 0) + 1
    state["retry_counts"][fingerprint] = count
    _record_result(state, result, result_digest, fingerprint)
    # Three failures are retryable; the fourth occurrence is the terminal
    # retry-exhausted observation.
    if count >= 4:
        _set_released(state, "FAILED_RETRY_EXHAUSTED", "FAILED_RETRY_EXHAUSTED", "human review required before changing the retry policy", result_digest)
    else:
        _set_released(state, "RESEARCH_PENDING", "RESEARCH_PENDING", "retry the same research stage with the recorded failure fingerprint", result_digest)


def _apply_invalid_result(state: dict[str, Any], detail: str) -> None:
    fingerprint = _failure_fingerprint("research", "worker_contract", detail)
    count = state["retry_counts"].get(fingerprint, 0) + 1
    state["retry_counts"][fingerprint] = count
    digest = _digest({"status": "FAILED", "error_fingerprint": fingerprint})
    state["history"].append({"attempt": state["attempts"], "stage": "research", "outcome": "FAILED", "result_digest": digest, "error_fingerprint": fingerprint})
    if count >= 4:
        _set_released(state, "FAILED_RETRY_EXHAUSTED", "FAILED_RETRY_EXHAUSTED", "human review required before changing the retry policy", digest)
    else:
        _set_released(state, "RESEARCH_PENDING", "RESEARCH_PENDING", "retry the worker after correcting its closed response contract", digest)


def _check_initial_args(state: dict[str, Any], child_repository: str, source_commit: str, project_path: str, allowed_paths: list[str]) -> None:
    if state["child_repository"] != child_repository or state["source_commit"] != source_commit or state["project_path"] != project_path or state["allowed_paths"] != allowed_paths:
        raise _error("resume inputs differ from the recorded run", "resume the same run_id with identical source and write-boundary metadata")


def run_autonomous(
    *,
    run_id: str,
    worker_command: str,
    state_root: Path | None = None,
    destinations_file: Path | None = None,
    child_repository: str = "agentic-art-research",
    source_commit: str | None = None,
    project_path: str = "project",
    allowed_paths: Iterable[str] = ("project",),
    owner: str | None = None,
    lease_seconds: int = 60,
    once: bool = False,
    max_steps: int = 32,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Run until a terminal state, or one checkpoint when ``once`` is true."""
    import re

    run_id = _safe_run_id(run_id)
    if not isinstance(worker_command, str) or not Path(worker_command).is_absolute():
        raise _error("worker command must be an absolute executable path", "pass --worker-command with an absolute path")
    worker = Path(worker_command)
    if not worker.is_file() or not os.access(worker, os.X_OK):
        raise _error("worker command does not exist", "provide the immutable worker executable")
    if lease_seconds <= 0 or max_steps <= 0:
        raise _error("lease_seconds and max_steps must be positive", "use bounded supervisor settings")
    if source_commit is None:
        source_commit = _git_head()
    if re.fullmatch(SHA40, source_commit) is None:
        raise _error("source_commit is not immutable", "pass a lowercase 40-character commit SHA")
    paths = _safe_relative_paths(allowed_paths)
    if not child_repository or not isinstance(child_repository, str):
        raise _error("child_repository is missing", "identify the worker child repository")
    destination_resolution = None
    project_root_selected = project_root is not None or PROJECT_ROOT_ENV in os.environ
    if project_root_selected and destinations_file is not None:
        raise _error("AMBIGUOUS_DESTINATION_MODE", "choose repo-local --project-root or output-destinations/v1")
    if project_root_selected:
        destination_resolution = resolve_project_root(project_root, run_id=run_id)
        state_root = Path(destination_resolution["destinations"]["state_root"]["path"])
        project_path = str(destination_resolution["project_root"])
    elif destinations_profile_selected(destinations_file):
        direct = {"state_root": state_root} if state_root is not None else None
        child_roots = ()
        project_root = Path(project_path).expanduser()
        if project_root.exists():
            child_roots = (project_root.resolve(),)
        destination_resolution = resolve_destinations(
            destinations_file,
            direct=direct,
            repository_root=ROOT,
            child_roots=child_roots,
            run_id=run_id,
        )
        state_root = Path(destination_resolution["destinations"]["state_root"]["path"])
    if state_root is None:
        raise _error("state-root is required", "pass --state-root or select an output-destinations/v1 profile")
    resolved_root = state_root.expanduser().resolve()
    try:
        resolved_root.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise _error("state-root must be outside the repository", "store supervisor state in an external run directory")
    run_dir = resolved_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if destination_resolution is not None:
        write_resolution_evidence(resolved_root, run_id, destination_resolution)
    state_path = run_dir / "supervisor.json"
    if state_path.exists():
        state = _load_object(state_path)
        state_errors = validate_autonomous_state(state)
        if state_errors:
            raise _error("existing supervisor state is invalid", state_errors[0])
        _check_initial_args(state, child_repository, source_commit, project_path, paths)
        if destination_resolution is not None and state.get("destination_resolution") != dict(destination_resolution):
            raise _error("existing supervisor state has different destination resolution", "resume with the same profile and run ID")
    else:
        state = _new_state(run_id, child_repository, source_commit, project_path, paths, _now())
        if destination_resolution is not None:
            state["destination_resolution"] = dict(destination_resolution)
        state_errors = validate_autonomous_state(state)
        if state_errors:
            raise _error("generated supervisor state is invalid", state_errors[0])
        _atomic_write(state_path, state)
    if state["status"] in TERMINAL_STATUSES:
        return state

    current_owner = owner or f"autonomous-runner-{os.getpid()}"
    execution_id = f"{run_id}:supervisor"
    expires = datetime.now(timezone.utc).timestamp() + lease_seconds
    expires_at = datetime.fromtimestamp(expires, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    lock = _lease_lock(run_dir, current_owner, expires_at, execution_id)
    try:
        state["lease"] = {"status": "held", "owner": current_owner, "expires_at": expires_at}
        _atomic_write(state_path, state)
        response_path = run_dir / "agent-result.json"
        steps = 0
        while state["status"] not in TERMINAL_STATUSES and steps < max_steps:
            steps += 1
            if response_path.exists():
                try:
                    result = _load_object(response_path)
                    result_errors = validate_agent_result(result)
                    if result.get("run_id") != run_id:
                        result_errors.append("agent-result.run_id differs from the requested run; remediation: return the same run_id")
                    if result_errors:
                        _apply_invalid_result(state, "invalid_result_contract")
                    else:
                        _apply_result(state, result, _digest(result))
                except AutonomousRunnerError:
                    _apply_invalid_result(state, "invalid_result_json")
                _atomic_write(state_path, state)
                try:
                    response_path.unlink()
                except FileNotFoundError:
                    pass
                if once or state["status"] in TERMINAL_STATUSES:
                    break
                continue

            if state["retry_counts"]:
                exhausted = next((count for count in state["retry_counts"].values() if count >= 3), None)
                if exhausted is not None and exhausted >= 4:
                    digest = _digest({"status": "FAILED_RETRY_EXHAUSTED", "run_id": run_id})
                    state["history"].append({"attempt": state["attempts"] + 1, "stage": "research", "outcome": "RETRY_EXHAUSTED", "result_digest": digest, "error_fingerprint": next(key for key, value in state["retry_counts"].items() if value >= 3)})
                    _set_released(state, "FAILED_RETRY_EXHAUSTED", "FAILED_RETRY_EXHAUSTED", "human review required before changing the retry policy", digest)
                    _atomic_write(state_path, state)
                    break

            state["attempts"] += 1
            action = _make_action(state, state["attempts"])
            request_path = _atomic_request(run_dir, action)
            state["status"] = "RESEARCH_WORKER_RUNNING"
            state["checkpoint"] = {"status": "RESEARCH_WORKER_RUNNING", "next_action": "await the provider-neutral worker response", "last_result_digest": state["checkpoint"].get("last_result_digest")}
            _atomic_write(state_path, state)
            environment = {key: value for key, value in os.environ.items() if not any(token in key.casefold() for token in ("token", "secret", "password", "credential", "api_key"))}
            try:
                completed = subprocess.run(
                    [str(worker), "--request", str(request_path), "--response", str(response_path)],
                    cwd=Path(project_path) if Path(project_path).is_dir() else None,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError:
                # Do not expose OS details or subprocess output in the
                # supervisor state. Treat an unlaunchable provider as a
                # repeatable contract failure.
                _apply_invalid_result(state, "worker_unlaunchable")
                _atomic_write(state_path, state)
                if once:
                    break
                continue
            if not response_path.exists():
                _apply_invalid_result(state, f"worker_exit_{completed.returncode}")
                _atomic_write(state_path, state)
            # If a response exists, process it at the top of the next iteration.
            if once:
                if response_path.exists():
                    continue
                break
        if state["status"] not in TERMINAL_STATUSES:
            state["lease"]["status"] = "available"
            state["lease"]["owner"] = "unassigned"
            _atomic_write(state_path, state)
        return state
    finally:
        _release_lock(lock)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle-context", type=Path, help="continue through the same canonical plan and native knowledge verifier")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--destinations-file", type=Path,
                        help="explicit external output-destinations/v1 profile")
    parser.add_argument("--project-root", type=Path,
                        help="explicit agentic-art-project checkout for output-destinations/v2")
    parser.add_argument("--worker-command", required=True)
    parser.add_argument("--child-repository", default="agentic-art-research")
    parser.add_argument("--source-commit")
    parser.add_argument("--project-path", default="project")
    parser.add_argument("--allowed-path", action="append", dest="allowed_paths")
    parser.add_argument("--owner")
    parser.add_argument("--lease-seconds", type=int, default=60)
    parser.add_argument("--max-steps", type=int, default=32)
    parser.add_argument("--once", action="store_true", help="execute one worker checkpoint and return")
    args = parser.parse_args()
    try:
        state = run_autonomous(
            run_id=args.run_id,
            worker_command=args.worker_command,
            state_root=args.state_root,
            destinations_file=args.destinations_file,
            child_repository=args.child_repository,
            source_commit=args.source_commit,
            project_path=args.project_path,
            allowed_paths=args.allowed_paths or ("project",),
            owner=args.owner,
            lease_seconds=args.lease_seconds,
            once=args.once,
            max_steps=args.max_steps,
            project_root=args.project_root,
        )
    except (OSError, TypeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.cycle_context is not None and state['status'] == 'RESEARCH_COMPLETE':
        from tools.knowledge_cycle_run import advance, read
        context = read(args.cycle_context)
        if context['run_id'] != args.run_id or args.state_root is None:
            raise ValueError('worker/cycle run binding and explicit state root required')
        if args.project_root is not None:
            selected = str(args.project_root.expanduser().resolve())
            if context.get('project_root') is not None and str(Path(context['project_root']).expanduser().resolve()) != selected:
                raise ValueError('PROJECT_ROOT_DESTINATION_CONFLICT')
            context['project_root'] = selected
        report = advance(context, args.state_root)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['run_status'] == 'COMPLETED' else 1
    print(json.dumps({"command": "autonomous-runner", "run_id": state["run_id"], "status": state["status"], "attempts": state["attempts"], "history_count": len(state["history"])}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
