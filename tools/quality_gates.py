#!/usr/bin/env python3
"""Run declared repository quality gates with safe, redacted evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
try:
    from tools.validate import COMMAND_FORBIDDEN_TOKENS
except ModuleNotFoundError:  # pragma: no cover - exercised by direct CLI use
    sys.path.insert(0, str(ROOT))
    from tools.validate import COMMAND_FORBIDDEN_TOKENS


class QualityGateError(ValueError):
    """The gate request or manifest cannot be executed safely."""


_SECRET_PATTERNS = [
    re.compile(
        r"(?i)\b(?:token|password|secret|api[_-]?key|private[_-]?key)\b\s*[:=]\s*([^\s,;]+)"
    ),
    re.compile(r"\b(?:ghp|github_pat|sk)-[A-Za-z0-9_-]{8,}\b"),
]


def redact_output(output: str) -> str:
    redacted = output
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(lambda match: match.group(0)[: match.start(1) - match.start(0)] + "<REDACTED>", redacted)
        else:
            redacted = pattern.sub("<REDACTED>", redacted)
    return redacted


def _output_evidence(stdout: str, stderr: str, max_output_chars: int = 4096) -> dict:
    combined = "".join(
        part for part in (stdout, stderr) if part
    )
    redacted = redact_output(combined)
    truncated = len(redacted) > max_output_chars
    visible = redacted[:max_output_chars]
    return {
        "output_redacted": visible,
        "output_truncated": truncated,
        "output_sha256": hashlib.sha256(redacted.encode("utf-8")).hexdigest(),
    }


def _gate_result(
    command: str,
    status: str,
    exit_code: int | None,
    duration_ms: int,
    stdout: str = "",
    stderr: str = "",
    error: str | None = None,
) -> dict:
    result = {
        "command": command,
        "status": status,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }
    result.update(_output_evidence(stdout, stderr))
    if error:
        result["error"] = error
    return result


def _run_gate(command: str, repository_path: Path, timeout_seconds: int) -> dict:
    if not isinstance(command, str) or not command.strip():
        return _gate_result(
            command if isinstance(command, str) else repr(command),
            "FAILED",
            None,
            0,
            error="empty quality gate command; remediation: declare one executable command",
        )
    if any(token in command for token in COMMAND_FORBIDDEN_TOKENS):
        return _gate_result(
            command,
            "FAILED",
            None,
            0,
            error="shell control syntax is forbidden; remediation: split the gate into safe commands",
        )
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return _gate_result(
            command,
            "FAILED",
            None,
            0,
            error=f"command parse failed: {exc}; remediation: quote command arguments safely",
        )
    if not argv:
        return _gate_result(
            command,
            "FAILED",
            None,
            0,
            error="command produced no argv; remediation: declare one executable command",
        )
    started = time.monotonic()
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join(
        [str(Path(sys.executable).parent), environment.get("PATH", "")]
    )
    try:
        completed = subprocess.run(
            argv,
            cwd=repository_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        status = "PASSED" if completed.returncode == 0 else "FAILED"
        return _gate_result(
            command,
            status,
            completed.returncode,
            duration_ms,
            completed.stdout,
            completed.stderr,
            None if completed.returncode == 0 else "quality gate returned non-zero; remediation: inspect redacted output and repair the owner repository",
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return _gate_result(
            command,
            "FAILED",
            None,
            duration_ms,
            stdout,
            stderr,
            "quality gate timed out; remediation: diagnose the owner repository before retrying",
        )
    except OSError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return _gate_result(
            command,
            "FAILED",
            None,
            duration_ms,
            error=f"quality gate could not start: {exc}; remediation: verify the declared executable and repository path",
        )


def run_quality_gates(
    manifest: dict,
    workspace_root: Path,
    changed_repositories: list[str] | set[str],
    timeout_seconds: int = 60,
) -> dict:
    """Run only changed repositories' manifest gates and return safe evidence."""
    repositories = manifest.get("repositories", []) if isinstance(manifest, dict) else []
    by_id = {repo.get("id"): repo for repo in repositories if isinstance(repo, dict)}
    changed = set(changed_repositories)
    unknown = sorted(changed - set(by_id))
    if unknown:
        raise QualityGateError(
            f"unknown changed repository IDs {unknown!r}; remediation: use IDs from config/repositories.yaml"
        )
    if timeout_seconds <= 0:
        raise QualityGateError("timeout_seconds must be positive; remediation: use a finite positive timeout")

    repository_results: list[dict] = []
    for repository_id in sorted(by_id):
        repository = by_id[repository_id]
        if repository_id not in changed:
            repository_results.append(
                {
                    "repository": repository_id,
                    "status": "NOT_RUN",
                    "reason": "repository unchanged; quality gate not required",
                    "gates": [],
                }
            )
            continue
        path = workspace_root / repository.get("path", "")
        commands = repository.get("quality_gates", [])
        if not path.is_dir():
            gates = [
                _gate_result(
                    str(command),
                    "FAILED",
                    None,
                    0,
                    error="repository path is missing; remediation: initialize the workspace before running gates",
                )
                for command in commands
            ]
        else:
            gates = [_run_gate(command, path, timeout_seconds) for command in commands]
        status = "FAILED" if any(gate["status"] == "FAILED" for gate in gates) else "PASSED"
        repository_results.append(
            {
                "repository": repository_id,
                "status": status,
                "gates": gates,
            }
        )

    failed = any(result["status"] == "FAILED" for result in repository_results)
    ran = any(result["status"] != "NOT_RUN" for result in repository_results)
    return {
        "status": "FAILED" if failed else ("PASSED" if ran else "NOT_RUN"),
        "blocking": failed,
        "repositories": repository_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run manifest quality gates for changed repositories")
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/repositories.yaml")
    parser.add_argument("--workspace-root", type=Path, default=ROOT / "repos")
    parser.add_argument("--changed", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    manifest_path = args.manifest if args.manifest.is_absolute() else Path.cwd() / args.manifest
    workspace_root = args.workspace_root if args.workspace_root.is_absolute() else Path.cwd() / args.workspace_root
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    try:
        result = run_quality_gates(manifest, workspace_root, args.changed, args.timeout)
    except QualityGateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result["blocking"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
