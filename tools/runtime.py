#!/usr/bin/env python3
"""Lease, retry, checkpoint, and resume state transitions for work items."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
import re


SHA40 = re.compile(r"^[0-9a-f]{40}$")
PR_URL = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*$")


class RuntimeTransitionError(ValueError):
    """A requested runtime transition is unsafe or not allowed."""


def _error(detail: str, remediation: str) -> RuntimeTransitionError:
    return RuntimeTransitionError(f"runtime: {detail}; remediation: {remediation}")


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise _error("timestamp must be a string", "use an ISO-8601 timestamp with timezone")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise _error(f"invalid timestamp {value!r}", "use an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise _error("timestamp must include timezone", "include Z or an explicit UTC offset")
    return parsed


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _copy_state(state: dict) -> dict:
    if not isinstance(state, dict):
        raise _error("work item state must be an object", "load one validated work item")
    return copy.deepcopy(state)


def _require_held(state: dict, owner: str) -> None:
    lease = state.get("lease", {})
    if state.get("terminal_state") != "IN_PROGRESS":
        raise _error(
            f"work item is not IN_PROGRESS ({state.get('terminal_state')!r})",
            "acquire a lease before changing active execution state",
        )
    if lease.get("status") != "held" or lease.get("owner") != owner:
        raise _error(
            "active lease owner does not match the worker",
            "resume with the recorded owner or wait for lease expiry",
        )


def acquire_lease(
    state: dict,
    owner: str,
    now: str,
    lease_minutes: int = 45,
) -> dict:
    """Acquire a lease, reusing the same execution ID after interruption."""
    next_state = _copy_state(state)
    if not owner or owner == "unassigned":
        raise _error("lease owner must be identified", "provide a worker owner")
    if next_state.get("terminal_state") in {"DONE", "BLOCKED"}:
        raise _error(
            f"terminal work item cannot be acquired ({next_state.get('terminal_state')})",
            "create a new work item instead of reopening terminal history",
        )
    lease = next_state.setdefault("lease", {})
    if lease.get("status") == "held":
        raise _error("lease is already held", "wait for its expiry or use the recorded owner")
    if next_state.get("terminal_state") != "READY":
        raise _error(
            f"only READY work can be acquired, got {next_state.get('terminal_state')!r}",
            "checkpoint the current state before returning it to READY",
        )
    if lease_minutes <= 0:
        raise _error("lease_minutes must be positive", "use the configured lease duration")
    started = _parse_timestamp(now)
    attempts = next_state.setdefault("attempts", {})
    used = attempts.get("used", 0)
    maximum = attempts.get("max", 1)
    checkpoint = next_state.setdefault("checkpoint", {})
    interrupted = checkpoint.get("last_result") == "interrupted" and checkpoint.get("execution_id")
    if not interrupted:
        if used >= maximum:
            raise _error(
                "retry budget is exhausted",
                "mark the work item BLOCKED or increase policy with human review",
            )
        used += 1
        attempts["used"] = used
        execution_id = f"{next_state.get('id', 'work-item')}:attempt-{used}"
    else:
        execution_id = checkpoint["execution_id"]

    expires = started + timedelta(minutes=lease_minutes)
    lease.update(
        {
            "status": "held",
            "owner": owner,
            "expires_at": _timestamp(expires),
            "execution_id": execution_id,
        }
    )
    next_state["terminal_state"] = "IN_PROGRESS"
    checkpoint.update(
        {
            "last_result": "running",
            "execution_id": execution_id,
            "next_action": checkpoint.get("next_action") or "execute the next checkpointed action",
        }
    )
    return next_state


def save_checkpoint(
    state: dict,
    owner: str,
    next_action: str,
    result: str = "checkpointed",
    decision: str | None = None,
) -> dict:
    next_state = _copy_state(state)
    _require_held(next_state, owner)
    if not next_action:
        raise _error("checkpoint next_action must be non-empty", "record the exact next safe operation")
    if result not in {"running", "checkpointed", "passed", "failed", "blocked"}:
        raise _error("checkpoint result is unknown", "use a supported checkpoint result")
    checkpoint = next_state.setdefault("checkpoint", {})
    checkpoint["next_action"] = next_action
    checkpoint["last_result"] = result
    if decision is not None:
        if not decision:
            raise _error("checkpoint decision must be non-empty", "record a concise observable decision")
        checkpoint["decision"] = decision
    return next_state


def record_evidence(
    state: dict,
    commits: list[str] | None = None,
    pull_requests: list[str] | None = None,
    tests: list[str] | None = None,
    changed_paths: list[str] | None = None,
) -> dict:
    """Append evidence idempotently so a resumed worker cannot duplicate it."""
    next_state = _copy_state(state)
    evidence = next_state.setdefault(
        "evidence", {"commits": [], "pull_requests": [], "tests": [], "changed_paths": []}
    )
    values = {
        "commits": commits or [],
        "pull_requests": pull_requests or [],
        "tests": tests or [],
        "changed_paths": changed_paths or [],
    }
    for commit in values["commits"]:
        if not isinstance(commit, str) or SHA40.fullmatch(commit) is None:
            raise _error(f"invalid commit evidence {commit!r}", "record a complete lowercase 40-character SHA")
    for pull_request in values["pull_requests"]:
        if not isinstance(pull_request, str) or PR_URL.fullmatch(pull_request) is None:
            raise _error(f"invalid pull request evidence {pull_request!r}", "record a canonical GitHub PR URL")
    for field, additions in values.items():
        existing = evidence.setdefault(field, [])
        for value in additions:
            if value not in existing:
                existing.append(value)
    return next_state


def expire_lease(state: dict, now: str) -> dict:
    """Release an expired lease while preserving checkpoint and decision context."""
    next_state = _copy_state(state)
    lease = next_state.get("lease", {})
    if lease.get("status") != "held":
        raise _error("lease is not held", "only an active lease can expire")
    current = _parse_timestamp(now)
    expiry = _parse_timestamp(lease.get("expires_at"))
    if current < expiry:
        raise _error("lease has not expired", "wait until expires_at or stop the worker explicitly")
    lease["status"] = "available"
    lease["owner"] = "unassigned"
    next_state["terminal_state"] = "READY"
    checkpoint = next_state.setdefault("checkpoint", {})
    checkpoint["last_result"] = "interrupted"
    checkpoint["next_action"] = checkpoint.get("next_action") or "resume from the last checkpoint"
    return next_state


def release_lease(state: dict, owner: str, result: str = "interrupted") -> dict:
    """Release a worker lease without losing the checkpoint."""
    next_state = _copy_state(state)
    _require_held(next_state, owner)
    if result not in {"interrupted", "failed"}:
        raise _error("release result must be interrupted or failed", "use complete_work_item for success")
    lease = next_state["lease"]
    lease["status"] = "available"
    lease["owner"] = "unassigned"
    next_state["terminal_state"] = "READY"
    next_state["checkpoint"]["last_result"] = result
    return next_state


def retry_or_block(state: dict, owner: str, reason: str) -> dict:
    """Return to READY within budget, otherwise transition to BLOCKED."""
    next_state = _copy_state(state)
    _require_held(next_state, owner)
    if not reason:
        raise _error("retry reason must be recorded", "record the observed failure before retrying")
    attempts = next_state["attempts"]
    lease = next_state["lease"]
    lease["status"] = "available"
    lease["owner"] = "unassigned"
    next_state["checkpoint"]["last_result"] = "failed"
    next_state["checkpoint"]["next_action"] = reason
    if attempts["used"] < attempts["max"]:
        next_state["terminal_state"] = "READY"
    else:
        next_state["terminal_state"] = "BLOCKED"
        next_state["checkpoint"]["last_result"] = "blocked"
    return next_state


def complete_work_item(state: dict, owner: str) -> dict:
    """Commit a terminal decision only once, requiring observable evidence."""
    next_state = _copy_state(state)
    if next_state.get("terminal_state") == "DONE":
        return next_state
    _require_held(next_state, owner)
    checkpoint = next_state.get("checkpoint", {})
    evidence = next_state.get("evidence", {})
    if checkpoint.get("last_result") != "passed":
        raise _error(
            "work item is not checkpointed as passed",
            "save a passed checkpoint after all acceptance checks",
        )
    if not evidence.get("commits") or not evidence.get("tests"):
        raise _error(
            "terminal completion requires commit and test evidence",
            "record observable evidence before DONE",
        )
    next_state["terminal_state"] = "DONE"
    next_state["lease"]["status"] = "available"
    next_state["lease"]["owner"] = "unassigned"
    checkpoint["next_action"] = "none"
    checkpoint["last_result"] = "passed"
    return next_state
