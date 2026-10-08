#!/usr/bin/env python3
"""Thin parent wrapper for the Self Model one-question hearing contract.

The packet returned by ``open`` is deliberately streamed to stdout and is
never written by this repository.  Only the outcome code is recorded in the
run state.  ``answer`` streams stdin directly to the child CLI so the parent
does not parse, retain, or log the person's response.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.process_policy import child_environment, observe_git_write_credentials
    from tools.validate import load_yaml
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.process_policy import child_environment, observe_git_write_credentials
    from tools.validate import load_yaml

from tools.profile_root_config import discover, redact, ProfileConfigError, REMEDIATION

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/repositories.yaml"
OUTCOME_CONTRACT = "self-hearing-outcome/v1"
DEFAULT_TIMEOUT = 30
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
HEARING_OUTCOMES = frozenset(("offered", "answered", "skipped", "unavailable", "not-run"))


class HearingWrapperError(RuntimeError):
    """A wrapper input or local state operation is invalid."""


class HearingUsageError(ValueError):
    """A malformed wrapper invocation, which still has the child contract's exit 0."""


class HearingArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # The wrapper is best-effort: usage errors must not stop the run.  A
        # valid run-id is required before an unavailable outcome is recorded.
        raise HearingUsageError(message)


def _valid_run_id(run_id: object) -> bool:
    return isinstance(run_id, str) and RUN_ID_PATTERN.fullmatch(run_id) is not None


def _valid_code(value: object) -> bool:
    return isinstance(value, str) and CODE_PATTERN.fullmatch(value) is not None


def _child_checkout(workspace_root: Path) -> Path:
    manifest = load_yaml(MANIFEST)
    repository = next((item for item in manifest.get("repositories", []) if item.get("id") == "self-model"), None)
    if not isinstance(repository, Mapping):
        raise HearingWrapperError("SELF_MODEL_REPOSITORY_MISSING")
    relative = Path(str(repository.get("path", "")))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise HearingWrapperError("SELF_MODEL_PATH_INVALID")
    return workspace_root / relative


def _hearing_command(
    checkout: Path,
    operation: str,
    *,
    profile_root: Path,
    requester: str,
    purpose: str,
    task_id: str | None = None,
    reason: str | None = None,
    expected_queue_sha256: str | None = None,
) -> list[str]:
    growth_tasks = checkout / "tools" / "growth_tasks.py"
    if not growth_tasks.is_file():
        raise HearingWrapperError("HEARING_UNAVAILABLE")
    command = [
        sys.executable,
        str(growth_tasks),
        "hearing",
        operation,
        "--profile-root",
        str(profile_root),
        "--requester",
        requester,
        "--purpose",
        purpose,
        "--json",
    ]
    if operation in {"answer", "skip"}:
        if not task_id:
            raise HearingWrapperError("TASK_ID_REQUIRED")
        command.insert(4, task_id)
    if operation == "skip":
        command.extend(["--reason", str(reason)])
    if operation == "answer" and expected_queue_sha256:
        command.extend(["--expected-queue-sha256", expected_queue_sha256])
    return command


def _parse_child_json(stdout: str) -> dict[str, Any] | None:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _outcome_path(state_root: Path, run_id: str) -> Path:
    return state_root / run_id / "hearing.json"


def _safe_unavailable(state_root: Path, run_id: str) -> dict[str, Any] | None:
    if not _valid_run_id(run_id):
        return None
    try:
        return _write_outcome(
            state_root, run_id, outcome="unavailable", reason="HEARING_UNAVAILABLE", question_id=None,
        )
    except (OSError, TypeError, ValueError):
        return None


def _write_outcome(
    state_root: Path,
    run_id: str,
    *,
    outcome: str,
    reason: str | None,
    question_id: str | None,
) -> dict[str, Any]:
    if (
        outcome not in HEARING_OUTCOMES
        or (reason is not None and not _valid_code(reason))
        or (question_id is not None and not _valid_code(question_id))
    ):
        outcome = "unavailable"
        reason = "HEARING_UNAVAILABLE"
        question_id = None
    document = {
        "contract_version": OUTCOME_CONTRACT,
        "run_id": run_id,
        "outcome": outcome,
        "reason": reason,
        "question_id": question_id,
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    path = _outcome_path(state_root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return document


def _record_credential_observation(state_root: Path, run_id: str, status: str, source: str = "none") -> None:
    """Create only a metadata stub for a pre-run hearing invocation.

    ``run.py`` replaces/extends this record with the real run report and keeps
    the same field.  No packet, answer, path, token, or helper output enters it.
    """
    path = state_root / run_id / "run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                existing = value
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing["run_id"] = run_id
    existing["git_write_credentials"] = status
    existing["profile_root_source"] = source
    path.write_text(json.dumps(existing, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def execute(
    operation: str,
    *,
    run_id: str,
    state_root: Path,
    workspace_root: Path,
    profile_root: Path | None = None,
    purpose: str = "artistic-research",
    task_id: str | None = None,
    reason: str | None = None,
    expected_queue_sha256: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    owner_answer: str | None = None,
    subject: str | None = None,
) -> tuple[int, str, dict[str, Any]]:
    """Run one child operation and return ``(exit_code, stdout, outcome)``."""
    if not _valid_run_id(run_id):
        # Never resolve an untrusted run id against the state root.
        return 0, "", {}
    try:
        profile_root, source = discover(profile_root)
        credential_status = observe_git_write_credentials(cwd=ROOT)
        if operation == "open":
            _record_credential_observation(state_root, run_id, credential_status, source)
    except Exception:
        outcome = _safe_unavailable(state_root, run_id) or {}
        return 0, "", outcome
    if profile_root is None:
        outcome = _write_outcome(state_root, run_id, outcome="unavailable",
                                 reason="PROFILE_ROOT_REQUIRED", question_id=None)
        return 0, json.dumps({"outcome": "unavailable", "reason": "PROFILE_ROOT_REQUIRED",
                              "remediation": REMEDIATION}, ensure_ascii=False) + "\n", outcome
    try:
        checkout = _child_checkout(workspace_root)
        from tools.hearing_elements import supports, relay
        progress_path = state_root / run_id / "hearing-element.json"
        use_element = operation in {"open", "next", "respond", "confirm"} and supports(checkout, timeout)
        if operation in {"answer", "skip"} and progress_path.is_file():
            use_element = json.loads(progress_path.read_text(encoding="utf-8")).get("private") is True
        if use_element:
            try:
                public, progress = relay(checkout, "next" if operation == "open" else operation,
                                         profile_root=profile_root, run_id=run_id, purpose=purpose, timeout=timeout,
                                         owner_answer=owner_answer, subject=subject)
                progress_path.parent.mkdir(parents=True, exist_ok=True)
                progress_path.write_text(json.dumps(progress, sort_keys=True) + "\n", encoding="utf-8")
                progress_path.chmod(0o600)
                outcome = _write_outcome(state_root, run_id,
                        outcome=public["outcome"],
                        reason="PRIVATE_ELEMENT_BLOCKED" if progress["status"] == "BLOCKED" else reason if progress["status"] == "SKIPPED" else None, question_id=progress.get("element_id"))
                return (2 if progress["status"] == "BLOCKED" else 0), json.dumps(public, ensure_ascii=False) + "\n", outcome
            except (ValueError, OSError, subprocess.TimeoutExpired):
                return 0, "", _safe_unavailable(state_root, run_id) or {}
        if operation in {"respond", "confirm"}:
            raise ValueError("PRIVATE_ELEMENT_UNAVAILABLE")
        command = _hearing_command(
            checkout,
            "open" if operation == "next" else operation,
            profile_root=profile_root,
            requester=run_id,
            purpose=purpose,
            task_id=task_id,
            reason=reason,
            expected_queue_sha256=expected_queue_sha256,
        )
    except Exception:
        outcome = _safe_unavailable(state_root, run_id) or {}
        return 0, "", outcome

    try:
        result = subprocess.run(
            command,
            cwd=checkout,
            stdin=sys.stdin if operation == "answer" else subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=child_environment(),
        )
    except (subprocess.TimeoutExpired, OSError):
        outcome = _safe_unavailable(state_root, run_id) or {}
        return 0, "", outcome

    result.stdout = redact(result.stdout, profile_root)
    child = _parse_child_json(result.stdout)
    if result.returncode != 0 or child is None:
        outcome = _safe_unavailable(state_root, run_id) or {}
        return 0, result.stdout, outcome

    child_outcome = child.get("outcome")
    if child_outcome not in HEARING_OUTCOMES:
        outcome = _safe_unavailable(state_root, run_id) or {}
        return 0, result.stdout, outcome
    child_reason = child.get("reason") if isinstance(child.get("reason"), str) else None
    question_id = child.get("question_id") if isinstance(child.get("question_id"), str) else None
    if (
        (child.get("reason") is not None and not _valid_code(child.get("reason")))
        or (child.get("question_id") is not None and not _valid_code(child.get("question_id")))
    ):
        outcome = _safe_unavailable(state_root, run_id) or {}
        return 0, result.stdout, outcome
    outcome = _write_outcome(
        state_root,
        run_id,
        outcome=str(child_outcome),
        reason=child_reason,
        question_id=question_id,
    )
    return 0, result.stdout, outcome


def main(argv: list[str] | None = None) -> int:
    parser = HearingArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True, parser_class=HearingArgumentParser)
    for operation in ("open", "next", "answer", "respond", "confirm", "skip"):
        command = sub.add_parser(operation)
        command.add_argument("--run-id", required=True)
        command.add_argument("--state-root", type=Path, required=True)
        command.add_argument("--workspace-root", type=Path, required=True)
        command.add_argument("--profile-root", type=Path, help="external profile; defaults to environment or owner local config")
        command.add_argument("--purpose", default="artistic-research")
        command.add_argument("--subject")
        if operation == "confirm":
            command.add_argument("--owner-answer", required=True, choices=("yes", "no"))
        command.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
        if operation in {"answer", "skip"}:
            command.add_argument("task_id_positional", nargs="?")
            command.add_argument("--task-id")
        if operation == "answer":
            command.add_argument("--expected-queue-sha256")
        if operation == "skip":
            command.add_argument("--reason", required=True, choices=("skipped", "no-response"))
    try:
        args = parser.parse_args(argv)
        task_id = getattr(args, "task_id", None) or getattr(args, "task_id_positional", None)
        if args.operation in {"answer", "skip"} and not task_id:
            progress = args.state_root / args.run_id / "hearing-element.json" if _valid_run_id(args.run_id) else None
            if progress is None or not progress.is_file() or json.loads(progress.read_text(encoding="utf-8")).get("private") is not True:
                parser.error(f"{args.operation} requires TASK_ID or --task-id")
        if not _valid_run_id(args.run_id):
            raise HearingUsageError("run-id must be a stable path-safe identifier")
        code, stdout, _ = execute(
            args.operation,
            run_id=args.run_id,
            state_root=args.state_root,
            workspace_root=args.workspace_root,
            profile_root=args.profile_root,
            purpose=args.purpose,
            task_id=task_id,
            reason=getattr(args, "reason", None),
            expected_queue_sha256=getattr(args, "expected_queue_sha256", None),
            timeout=args.timeout,
            owner_answer=getattr(args, "owner_answer", None),
            subject=args.subject,
        )
    except HearingUsageError:
        # There may be no safely parsed state-root/run-id pair to record.  The
        # child contract still requires a successful, traceback-free wrapper.
        return 0
    except Exception:
        # YAML/filesystem failures are unavailable infrastructure.  Record only
        # the sanitized outcome when parsed arguments make that safe.
        try:
            if "args" in locals() and _valid_run_id(getattr(args, "run_id", None)):
                _safe_unavailable(args.state_root, args.run_id)
        except Exception:
            pass
        return 0
    # ``open`` must expose the packet exactly as returned by the child.  The
    # other operations only return the child's structured acknowledgement.
    if stdout:
        sys.stdout.write(stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
