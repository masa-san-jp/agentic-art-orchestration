#!/usr/bin/env python3
"""Run read-only release qualification checks without releasing anything."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASYNC_AUDIT_FIXTURE_STATE = ROOT / "tests/fixtures/async-audit/state.yaml"
V12_FIXTURE = ROOT / "tests/fixtures/v12-candidates"
V12_MANIFEST = ROOT / "config/repositories.yaml"
V12_WORKSPACE_ROOT = ROOT / "repos"
GITHUB_SANDBOX_EVIDENCE_SCHEMA = ROOT / "schemas/github-sandbox-live-evidence.schema.json"
GITHUB_SANDBOX_LIVE_POLICY = ROOT / "config/github-sandbox-live-policy.yaml"
# The offline qualification contract uses a stable observation epoch so reports remain byte-reproducible.
QUALIFICATION_OBSERVED_AT = "2026-08-25T18:48:41+09:00"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.e2e import run_e2e
from tools.child_quality_gates import run_child_quality_gates
from tools.production_exchange import run_exchange_e2e
from tools.pinned_workspace import PinnedWorkspaceError, materialize_pinned_workspace
from tools.validate import _schema_errors, load_json, load_yaml
from tools.v12_e2e import run_v12_e2e
from tools.interaction_e2e import run_interaction_e2e
from tools.initial_operations_e2e import run_initial_operations_e2e


class ReleaseCheckError(ValueError):
    """A release qualification request or result is invalid."""


SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|secret|api[_-]?key|private[_-]?key|credential)\b\s*[:=]\s*([^\s,;\"'{}()\[\]]+)"
)
TOKEN_VALUE = re.compile(r"\b(?:ghp|github_pat|sk)-[A-Za-z0-9_-]{8,}\b")
FORBIDDEN_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:PRIVATE_RAW|RESTRICTED|direct_identifier|raw_voice_body|raw_voice_text|raw_audio)\s*[:=]"
)
HISTORY_EXEMPT_PREFIXES = ("docs/", "execution/", "tests/")
HISTORY_EXEMPT_VALUES = {"supersecret", "synthetic-value", "synthetic-secret"}


def _active_python() -> str:
    """Return the interpreter from the active virtualenv when one is present."""
    prefix = Path(sys.prefix)
    base_prefix = Path(getattr(sys, "base_prefix", sys.prefix))
    if prefix != base_prefix:
        for name in ("python", "python3"):
            candidate = prefix / "bin" / name
            if candidate.is_file():
                return str(candidate)
    return sys.executable


def _run(command: list[str]) -> tuple[int, str, str]:
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join(
        [str(Path(_active_python()).parent), environment.get("PATH", "")]
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        # Git history can contain binary blobs. Preserve undecodable bytes so
        # ASCII credential patterns are still scanned instead of skipping blobs.
        errors="surrogateescape",
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _git(command: list[str]) -> str:
    code, stdout, stderr = _run(["git", *command])
    if code:
        raise ReleaseCheckError(f"git inspection failed: {command[0]}")
    return stdout


def validate_request(version: str, runs: int) -> None:
    if version not in {"1.0.0", "1.1.0", "1.2.0", "1.2.1", "1.3.0", "1.4.0"}:
        raise ReleaseCheckError("only versions 1.0.0, 1.1.0, 1.2.0, 1.2.1, 1.3.0, and 1.4.0 are supported; remediation: qualify the declared task version")
    if runs <= 0:
        raise ReleaseCheckError("runs must be positive; remediation: use at least one deterministic E2E run")


def _history_paths(commit: str) -> list[str]:
    output = _git(["diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit])
    return [line for line in output.splitlines() if line]


def _history_forbidden_findings() -> dict:
    """Scan committed non-fixture content without returning sensitive values."""
    commits = [line for line in _git(["rev-list", "--all"]).splitlines() if line]
    findings: list[dict] = []
    for commit in commits:
        for path in _history_paths(commit):
            if path.startswith(HISTORY_EXEMPT_PREFIXES):
                continue
            code, stdout, _ = _run(["git", "show", f"{commit}:{path}"])
            if code:
                continue
            text = stdout
            secret_match = SECRET_ASSIGNMENT.search(text)
            token_match = TOKEN_VALUE.search(text)
            forbidden_match = FORBIDDEN_ASSIGNMENT.search(text)
            if secret_match and secret_match.group(1) in HISTORY_EXEMPT_VALUES:
                secret_match = None
            if secret_match or token_match or forbidden_match:
                findings.append(
                    {
                        "commit": commit,
                        "path": path,
                        "reason": "credential-like or forbidden assignment pattern",
                    }
                )
    return {
        "status": "PASSED" if not findings else "FAILED",
        "commit_count": len(commits),
        "finding_count": len(findings),
        "findings": findings,
    }


def _command_check(identifier: str, command: list[str]) -> dict:
    code, _, _ = _run(command)
    return {
        "id": identifier,
        "status": "PASSED" if code == 0 else "FAILED",
        "exit_code": code,
    }


def _observation_provenance(item: dict, evidence_locator: str) -> dict:
    """Return a sanitized, explicit provenance envelope for a qualification observation."""
    repository = item.get("repository")
    observed_commit = item.get("observed_commit")
    source_head = item.get("source_head")
    unknowns = {"remote_head_not_observed"}
    if source_head is None:
        unknowns.add("local_worktree_head_unavailable")
    elif observed_commit is None:
        unknowns.add("manifest_pin_unavailable")
    elif source_head != observed_commit:
        unknowns.add("local_worktree_differs_from_manifest_pin")
    return {
        "repository": repository,
        "source_repository": repository,
        "observed_ref": observed_commit,
        "source_commit": observed_commit,
        "observed_via": "manifest_pin",
        "observed_at": QUALIFICATION_OBSERVED_AT,
        "evidence_locator": evidence_locator,
        "local_worktree": {
            "head": source_head,
            "matches_manifest_pin": (
                source_head == observed_commit
                if source_head is not None and observed_commit is not None
                else None
            ),
            "matches_remote_head": None,
        },
        "unknowns": sorted(unknowns),
    }


def _child_repository_observation(result: dict, index: int, locator_prefix: str) -> dict:
    """Keep child gate findings tied to their immutable source and evidence reference."""
    provenance = _observation_provenance(
        result,
        f"release-check://{locator_prefix}/{result.get('repository', index)}",
    )
    observation = {
        "repository": result.get("repository"),
        "observed_commit": result.get("observed_commit"),
        "workspace_commit": result.get("workspace_commit"),
        "workspace_state": result.get("workspace_state"),
        "execution_mode": result.get("execution_mode"),
        "status": result.get("status"),
        "gate_statuses": [
            gate.get("status")
            for gate in result.get("gates", [])
            if isinstance(gate, dict)
        ],
        **provenance,
    }
    if "environment_mode" in result:
        observation["environment_mode"] = result["environment_mode"]
    return observation


def _e2e_check(runs: int) -> dict:
    results: list[dict] = []
    error_types: list[str] = []
    for _ in range(runs):
        try:
            results.append(run_e2e())
        except Exception as exc:  # qualification report must remain sanitized
            error_types.append(type(exc).__name__)
    deterministic = bool(results) and len(results) == runs and all(result == results[0] for result in results[1:])
    clean_complete = bool(results) and all(result.get("clean", {}).get("status") == "COMPLETE" for result in results)
    failure_cases = [
        len(result.get("failure_injections", []))
        for result in results
        if isinstance(result, dict)
    ]
    passed = deterministic and clean_complete and failure_cases and all(count == 9 for count in failure_cases)
    return {
        "id": "offline-e2e",
        "status": "PASSED" if passed else "FAILED",
        "runs": runs,
        "deterministic": deterministic,
        "clean_complete": clean_complete,
        "failure_case_counts": failure_cases,
        "error_types": sorted(set(error_types)),
    }


def _interaction_e2e_check(runs: int) -> dict:
    """Qualify the v1.1 frontstage/backstage scenario without retaining content."""
    summaries: list[dict] = []
    error_types: list[str] = []
    for _ in range(runs):
        try:
            result = run_interaction_e2e()
            acceptance = result.get("acceptance", {})
            summaries.append(
                {
                    "acceptance": {
                        key: acceptance.get(key) is True
                        for key in sorted(acceptance)
                    },
                    "artifact_operation": result.get("artifact", {}).get("operation"),
                    "security_status": result.get("security", {}).get("status"),
                    "remote_operation_count": len(result.get("remote_operations", [])),
                    "routing_operation_count": len(result.get("routing", {}).get("issue_operations", [])),
                    "improvement_operation_count": len(result.get("improvement", {}).get("remote_operations", [])),
                    "audit_operation_count": len(result.get("audit", {}).get("artifact_operations", [])),
                }
            )
        except Exception as exc:  # qualification report must remain sanitized
            error_types.append(type(exc).__name__)
    deterministic = bool(summaries) and len(summaries) == runs and all(
        summary == summaries[0] for summary in summaries[1:]
    )
    required_acceptance = {
        "retrieval_versioned",
        "artifact_immutable",
        "feedback_captured",
        "issue_routed",
        "improvement_checkpointed",
        "audit_independent",
        "no_remote_mutation",
    }
    acceptance_passed = bool(summaries) and all(
        required_acceptance.issubset(summary["acceptance"])
        and all(summary["acceptance"].get(key) is True for key in required_acceptance)
        for summary in summaries
    )
    no_remote_mutation = bool(summaries) and all(
        summary["artifact_operation"] == "CREATE"
        and summary["security_status"] == "PASSED"
        and summary["remote_operation_count"] == 0
        and summary["routing_operation_count"] == 0
        and summary["improvement_operation_count"] == 0
        and summary["audit_operation_count"] == 0
        for summary in summaries
    )
    passed = deterministic and acceptance_passed and no_remote_mutation
    return {
        "id": "interaction-e2e",
        "status": "PASSED" if passed else "FAILED",
        "runs": runs,
        "deterministic": deterministic,
        "acceptance_passed": acceptance_passed,
        "no_remote_mutation": no_remote_mutation,
        "error_types": sorted(set(error_types)),
    }


def _initial_operations_e2e_check(runs: int) -> dict:
    """Qualify the initial operations contract without external writes."""
    summaries: list[dict] = []
    error_types: list[str] = []
    for index in range(runs):
        try:
            result = run_initial_operations_e2e(run_id=f"INITIAL-OPS-QUALIFY-001:run-{index + 1}", offline_fixture=True)
            summaries.append(
                {
                    "acceptance": {key: value is True for key, value in sorted(result["acceptance"].items())},
                    "startup_status": result["startup"]["status"],
                    "retrieval_status": result["retrieval"]["status"],
                    "drive": {
                        "create_status": result["drive"]["create_status"],
                        "replay_status": result["drive"]["replay_status"],
                        "provider_file_count": result["drive"]["provider_file_count"],
                    },
                    "issue": {
                        "create_status": result["issue"]["create"]["status"],
                        "reuse_status": result["issue"]["reuse"]["status"],
                    },
                    "live_gate": result["live_gate"]["status"],
                    "remote_operation_count": len(result["remote_operations"]),
                }
            )
        except Exception as exc:
            error_types.append(type(exc).__name__)
    deterministic = bool(summaries) and len(summaries) == runs and all(summary == summaries[0] for summary in summaries[1:])
    acceptance_passed = bool(summaries) and all(all(summary["acceptance"].values()) for summary in summaries)
    no_remote_mutation = bool(summaries) and all(summary["remote_operation_count"] == 0 for summary in summaries)
    drive_idempotent = bool(summaries) and all(
        summary["drive"] == {"create_status": "CREATED", "replay_status": "REPLAYED", "provider_file_count": 1}
        for summary in summaries
    )
    issue_idempotent = bool(summaries) and all(
        summary["issue"] == {"create_status": "CREATED", "reuse_status": "REUSED"}
        for summary in summaries
    )
    live_gate_closed = bool(summaries) and all(summary["live_gate"] == "NOT_REQUESTED" for summary in summaries)
    passed = deterministic and acceptance_passed and no_remote_mutation and drive_idempotent and issue_idempotent and live_gate_closed and not error_types
    return {
        "id": "initial-operations-e2e",
        "status": "PASSED" if passed else "FAILED",
        "runs": runs,
        "deterministic": deterministic,
        "acceptance_passed": acceptance_passed,
        "drive_idempotent": drive_idempotent,
        "issue_idempotent": issue_idempotent,
        "live_gate_closed": live_gate_closed,
        "no_remote_mutation": no_remote_mutation,
        "error_types": sorted(set(error_types)),
    }


def _v12_e2e_check(
    runs: int,
    workspace_root: Path = V12_WORKSPACE_ROOT,
    child_quality_gates: dict | None = None,
) -> dict:
    """Qualify v1.2 and require every pinned child quality gate to pass."""
    summaries: list[dict] = []
    error_types: list[str] = []
    for index in range(runs):
        try:
            result = run_v12_e2e(
                run_id=f"V12-RELEASE-001:attempt-{index + 1}",
                fixture_dir=V12_FIXTURE,
                manifest_path=V12_MANIFEST,
                workspace_root=workspace_root,
                child_quality_gates=child_quality_gates,
            )
            summaries.append(
                {
                    "acceptance": {
                        key: result["acceptance"].get(key) is True
                        for key in sorted(result["acceptance"])
                    },
                    "child_statuses": result["child_quality_gates"]["statuses"],
                    "child_workspace_states": result["child_quality_gates"]["workspace_states"],
                    "child_execution_modes": result["child_quality_gates"]["execution_modes"],
                    "child_environment_modes": sorted(
                        {
                            item.get("environment_mode", "shared-runner")
                            for item in (child_quality_gates or {}).get("results", [])
                            if isinstance(item, dict)
                        }
                    ),
                    "remote_operations": result["remote_operations"],
                }
            )
        except Exception as exc:  # qualification report must remain sanitized
            error_types.append(type(exc).__name__)
    deterministic = bool(summaries) and len(summaries) == runs and all(
        summary == summaries[0] for summary in summaries[1:]
    )
    acceptance_passed = bool(summaries) and all(
        all(summary["acceptance"].values()) for summary in summaries
    )
    child_gates_passed = bool(summaries) and all(
        summary["child_statuses"] == ["PASSED"]
        and summary["child_execution_modes"] == ["immutable-archive"]
        for summary in summaries
    )
    no_remote_mutation = bool(summaries) and all(
        summary["remote_operations"] == [] for summary in summaries
    )
    passed = deterministic and acceptance_passed and child_gates_passed and no_remote_mutation
    return {
        "id": "v1.2-e2e",
        "status": "PASSED" if passed else "FAILED",
        "runs": runs,
        "deterministic": deterministic,
        "acceptance_passed": acceptance_passed,
        "child_gates_passed": child_gates_passed,
        "no_remote_mutation": no_remote_mutation,
        "error_types": sorted(set(error_types)),
        "child_statuses": summaries[0]["child_statuses"] if summaries else [],
        "child_workspace_states": summaries[0]["child_workspace_states"] if summaries else [],
        "child_execution_modes": summaries[0]["child_execution_modes"] if summaries else [],
        "child_environment_modes": summaries[0]["child_environment_modes"] if summaries else [],
    }


def _v12_child_quality_gate_check(
    report_path: Path = ROOT / "data/child-quality-gates.json",
) -> dict:
    """Require the materialized child-gate report to contain only PASS results."""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "id": "v1.2-child-quality-gates-result",
            "status": "FAILED",
            "repository_count": 0,
            "repository_statuses": [],
            "gate_statuses": [],
            "execution_modes": [],
        }
    results = report.get("results", [])
    repository_statuses = sorted({item.get("status") for item in results})
    gate_statuses = sorted(
        {
            gate.get("status")
            for item in results
            for gate in item.get("gates", [])
        }
    )
    execution_modes = sorted({item.get("execution_mode") for item in results})
    passed = bool(results) and repository_statuses == ["PASSED"] and gate_statuses == ["PASSED"]
    repository_observations = [
        _child_repository_observation(item, index, "v1.2-child-quality-gates")
        for index, item in enumerate(results)
        if isinstance(item, dict)
    ]
    return {
        "id": "v1.2-child-quality-gates-result",
        "status": "PASSED" if passed else "FAILED",
        "repository_count": len(results),
        "repository_statuses": repository_statuses,
        "gate_statuses": gate_statuses,
        "execution_modes": execution_modes,
        "repository_observations": repository_observations,
    }


def _v12_release_checks(
    python: str,
    workspace_root: Path,
    child_quality_gates: dict | None = None,
) -> list[dict]:
    """Materialize v1.2 child and E2E evidence in an isolated temporary directory."""
    with tempfile.TemporaryDirectory(prefix="release-v12-") as temporary_name:
        temporary = Path(temporary_name)
        child_report = temporary / "child-quality-gates.json"
        e2e_report = temporary / "v12-e2e.json"
        if child_quality_gates is None:
            checks = [
                _command_check(
                    "v1.2-child-quality-gates",
                    [
                        python,
                        "tools/child_quality_gates.py",
                        "--manifest",
                        str(V12_MANIFEST),
                        "--workspace-root",
                        str(workspace_root),
                        "--run-id",
                        "v12-child-gates",
                        "--output",
                        str(child_report),
                    ],
                )
            ]
        else:
            child_report.write_text(json.dumps(child_quality_gates, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            checks = []
        checks.extend([
            _command_check(
                "v1.2-e2e-materialize",
                [
                    python,
                    "tools/v12_e2e.py",
                    "--run-id",
                    "v12-e2e",
                    "--fixture",
                    str(V12_FIXTURE),
                    "--manifest",
                    str(V12_MANIFEST),
                    "--workspace-root",
                    str(workspace_root),
                    "--child-quality-gates",
                    str(child_report),
                    "--output",
                    str(e2e_report),
                ],
            ),
            _v12_child_quality_gate_check(child_report),
        ])
        return checks


def _child_gate_summary(report: dict, manifest: dict) -> dict:
    """Reduce child gate evidence to release-safe observations."""
    results = report.get("results", [])
    gate_statuses = [
        gate.get("status")
        for result in results
        for gate in result.get("gates", [])
    ]
    repositories = manifest.get("repositories", []) if isinstance(manifest, dict) else []
    expected_repository_count = len(repositories)
    expected_gate_count = sum(
        len(repository.get("quality_gates", []))
        for repository in repositories
        if isinstance(repository, dict) and isinstance(repository.get("quality_gates", []), list)
    )
    repositories_match = all(
        result.get("workspace_state") == "MATCHED"
        and result.get("workspace_commit") == result.get("observed_commit")
        for result in results
    )
    passed = (
        len(results) == expected_repository_count
        and repositories_match
        and all(result.get("status") == "PASSED" for result in results)
        and len(gate_statuses) == expected_gate_count
        and all(status == "PASSED" for status in gate_statuses)
        and all(result.get("execution_mode") == "immutable-archive" for result in results)
    )
    repository_observations = [
        _child_repository_observation(result, index, "production-child-gates")
        for index, result in enumerate(results)
        if isinstance(result, dict)
    ]
    return {
        "status": "PASSED" if passed else "FAILED",
        "repository_count": len(results),
        "gate_count": len(gate_statuses),
        "repository_statuses": sorted({result.get("status") for result in results}),
        "gate_statuses": sorted(set(gate_statuses)),
        "workspace_states": sorted({result.get("workspace_state") for result in results}),
        "execution_modes": sorted({result.get("execution_mode") for result in results}),
        "environment_modes": sorted({result.get("environment_mode", "shared-runner") for result in results}),
        "repositories_match_recorded_commits": repositories_match,
        "repository_observations": repository_observations,
    }


def _production_exchange_check(
    runs: int,
    workspace_root: Path,
    child_python: str,
    child_quality_gates: dict | None = None,
    python_root: Path | None = None,
    child_timeout_seconds: int = 60,
) -> dict:
    """Qualify the Production exchange without retaining child or bundle content."""
    manifest = load_yaml(V12_MANIFEST)
    e2e_reports: list[dict] = []
    e2e_bytes: list[bytes] = []
    child_summaries: list[dict] = []
    error_types: list[str] = []
    generated_at = "2026-08-13T09:00:00+09:00"
    with tempfile.TemporaryDirectory(prefix="release-production-") as temporary_name:
        temporary = Path(temporary_name)
        for index in range(runs):
            try:
                report = run_exchange_e2e(
                    manifest,
                    workspace_root,
                    temporary / f"exchange-{index + 1}",
                    run_id="PRODUCTION-QUALIFY-001",
                    generated_at=generated_at,
                    child_python=child_python,
                )
                rendered = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
                e2e_reports.append(report)
                e2e_bytes.append(rendered)
                child_report = (
                    child_quality_gates
                    if child_quality_gates is not None
                    else run_child_quality_gates(
                        manifest,
                        workspace_root,
                        run_id=f"PRODUCTION-QUALIFY-001:child-{index + 1}",
                        python_root=python_root,
                        timeout_seconds=child_timeout_seconds,
                    )
                )
                child_summaries.append(_child_gate_summary(child_report, manifest))
            except Exception as exc:  # qualification report must remain sanitized
                error_types.append(type(exc).__name__)
    deterministic = bool(e2e_bytes) and len(e2e_bytes) == runs and all(
        observed == e2e_bytes[0] for observed in e2e_bytes[1:]
    )
    expected_scenarios = {
        "clean": ("PASSED", "COMPLETE"),
        "tamper": ("FAILED", "FAILED"),
        "stale": ("BLOCKED", "BLOCKED"),
        "incompatible": ("FAILED", "FAILED"),
        "dirty-source": ("BLOCKED", "BLOCKED"),
        "replay": ("PASSED", "REPLAYED"),
    }
    scenario_matrix_passed = bool(e2e_reports) and all(
        {
            item.get("scenario_id"): (item.get("status"), item.get("terminal_status"))
            for item in report.get("scenarios", [])
        }
        == expected_scenarios
        for report in e2e_reports
    )
    no_effects = bool(e2e_reports) and all(
        report.get("remote_operations") == []
        and report.get("child_mutations") == []
        and report.get("normal_exchange", {}).get("status") == "PASSED"
        and report.get("normal_exchange", {}).get("external_validation_required") is True
        and report.get("normal_exchange", {}).get("research_result_dry_run") is True
        for report in e2e_reports
    )
    child_gates_passed = bool(child_summaries) and len(child_summaries) == runs and all(
        summary["status"] == "PASSED" for summary in child_summaries
    )
    tracked_outputs = [
        path
        for path in _git(
            [
                "ls-files",
                "--",
                "data/production-exchange.json",
                "data/release-check.json",
                "data/child-quality-gates.json",
            ]
        ).splitlines()
        if path
    ]
    git_external_outputs = not tracked_outputs
    passed = (
        deterministic
        and scenario_matrix_passed
        and no_effects
        and child_gates_passed
        and git_external_outputs
        and not error_types
    )
    return {
        "id": "production-exchange",
        "status": "PASSED" if passed else "FAILED",
        "runs": runs,
        "deterministic": deterministic,
        "report_sha256": ["sha256:" + hashlib.sha256(value).hexdigest() for value in e2e_bytes],
        "scenario_matrix_passed": scenario_matrix_passed,
        "child_gates_passed": child_gates_passed,
        "child_gate_runs": child_summaries,
        "git_external_outputs": git_external_outputs,
        "tracked_output_paths": tracked_outputs,
        "no_physical_or_remote_effect": no_effects,
        "error_types": sorted(set(error_types)),
    }


def _sandbox_live_evidence_check(evidence_path: Path | None = None) -> dict:
    """Validate supplied metadata-only live evidence without performing a remote write."""
    base = {
        "id": "initial-operations-live-evidence",
        "drive_create_read": "PASSED",
        "required_controls": ["approved_sandbox", "credential_outside_git", "explicit_confirmation", "single_live_lane"],
        "remote_operations": [],
    }
    if evidence_path is None:
        return {
            **base,
            "status": "BLOCKED",
            "github_issue_create_reuse": "NOT_AVAILABLE",
            "reason": "no explicitly approved GitHub sandbox evidence was supplied; no Issue CREATE was attempted",
        }
    try:
        evidence = load_json(evidence_path)
    except (OSError, ValueError):
        return {
            **base,
            "status": "FAILED",
            "github_issue_create_reuse": "FAILED",
            "reason": "sandbox evidence could not be read",
        }
    schema_errors = _schema_errors(evidence, load_json(GITHUB_SANDBOX_EVIDENCE_SCHEMA))
    if schema_errors or not isinstance(evidence, dict):
        return {
            **base,
            "status": "FAILED",
            "github_issue_create_reuse": "FAILED",
            "reason": "sandbox evidence violates the closed metadata-only schema",
        }
    operations = evidence["remote_operations"]
    operation_names = [item["operation"] for item in operations]
    repository_hash = evidence["repository_id_hash"]
    idempotency_hash = evidence["idempotency_key_hash"]
    consistent = all(
        item["repository_id_hash"] == repository_hash
        and item["idempotency_key_hash"] == idempotency_hash
        for item in operations
    )
    create_index = operation_names.index("CREATE") if "CREATE" in operation_names else -1
    reuse_index = operation_names.index("REUSE") if "REUSE" in operation_names else -1
    retry_policy = load_yaml(GITHUB_SANDBOX_LIVE_POLICY).get("post_create_search", {})
    max_attempts = retry_policy.get("max_attempts") if isinstance(retry_policy, dict) else None
    post_create_reads = operations[2:-1]
    post_create_attempts = [item.get("attempt") for item in post_create_reads]
    bounded_retry_evidence = (
        isinstance(max_attempts, int)
        and 1 <= len(post_create_reads) <= max_attempts
        and (
            post_create_attempts == list(range(1, len(post_create_reads) + 1))
            or post_create_attempts == [None]
        )
    )
    fresh_create_reuse = (
        evidence["mode"] == "LIVE"
        and evidence["status"] == "CREATED"
        and evidence["operation"] == "CREATE"
        and evidence["issue_id_hash"] is not None
        and operation_names[0:2] == ["READ", "CREATE"]
        and create_index == 1
        and reuse_index == len(operation_names) - 1
        and len(operation_names) >= 4
        and all(item == "READ" for item in operation_names[2:-1])
        and sum(item == "CREATE" for item in operation_names) == 1
        and bounded_retry_evidence
        and consistent
    )
    if not fresh_create_reuse:
        return {
            **base,
            "status": "BLOCKED" if evidence.get("status") == "REUSED" else "FAILED",
            "github_issue_create_reuse": "NOT_AVAILABLE" if evidence.get("status") == "REUSED" else "FAILED",
            "remote_operations": operations,
            "reason": "live evidence must prove a fresh single CREATE followed by a deduplicated REUSE",
        }
    return {
        **base,
        "status": "PASSED",
        "github_issue_create_reuse": "PASSED",
        "remote_operations": operations,
        "reason": "dedicated sandbox Issue CREATE and REUSE evidence validated",
    }


def _qualify(
    version: str = "1.0.0",
    runs: int = 3,
    workspace_root: Path = V12_WORKSPACE_ROOT,
    github_sandbox_evidence: Path | None = None,
    pinned_observations: list[dict] | None = None,
    python_root: Path | None = None,
    child_timeout_seconds: int = 60,
) -> dict:
    """Return a deterministic qualification report; never create a tag, commit, or release."""
    validate_request(version, runs)
    python = _active_python()
    child_quality_gates = None
    if version in {"1.2.0", "1.2.1", "1.3.0", "1.4.0"}:
        child_quality_gates = run_child_quality_gates(
            load_yaml(V12_MANIFEST),
            workspace_root,
            timeout_seconds=child_timeout_seconds,
            run_id="release-qualification-child-gates",
            python_root=python_root,
        )
    checks = [
        _command_check("status-materialize", [python, "tools/status.py", "--offline-fixture"]),
        _command_check("audit-materialize", [python, "tools/audit.py", "--offline-fixture"]),
    ]
    if version in {"1.1.0", "1.2.0", "1.2.1", "1.3.0", "1.4.0"}:
        checks.extend(
            [
                _command_check("retrieval-materialize", [python, "tools/retrieval.py"]),
                _command_check("feedback-routing-materialize", [python, "tools/issue_router.py"]),
                _command_check("improvement-materialize", [python, "tools/improvement_loop.py"]),
                _command_check(
                    "async-audit-materialize",
                    [python, "tools/async_auditor.py", "--state", str(ASYNC_AUDIT_FIXTURE_STATE)],
                ),
                _command_check("interaction-e2e-materialize", [python, "tools/interaction_e2e.py"]),
            ]
        )
    if version == "1.4.0":
        checks.extend(
            [
                _command_check("initial-operations-e2e-materialize", [python, "tools/initial_operations_e2e.py", "--offline-fixture"]),
                _command_check("initial-operations-e2e-tests", [python, "-m", "unittest", "tests.test_initial_operations_e2e"]),
            ]
        )
    checks.extend(
        [
            _command_check("parent-validator", [python, "tools/validate.py", "--check"]),
            _command_check("parent-tests", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]),
            _command_check("offline-fixture", [python, "tests/fixtures/build_fixture.py", "--check"]),
            _command_check("status", [python, "tools/status.py", "--check", "--offline-fixture"]),
            _command_check("audit", [python, "tools/audit.py", "--check", "--offline-fixture"]),
            _command_check("security", [python, "tools/security.py", "--offline-fixture"]),
        ]
    )
    if version in {"1.1.0", "1.2.0", "1.2.1", "1.3.0", "1.4.0"}:
        checks.extend(
            [
                _command_check("retrieval", [python, "tools/retrieval.py", "--check"]),
                _command_check("feedback-routing", [python, "tools/issue_router.py", "--check"]),
                _command_check("improvement", [python, "tools/improvement_loop.py", "--check"]),
                _command_check(
                    "async-audit",
                    [
                        python,
                        "tools/async_auditor.py",
                        "--state",
                        str(ASYNC_AUDIT_FIXTURE_STATE),
                        "--check",
                    ],
                ),
                _command_check("interaction-e2e", [python, "tools/interaction_e2e.py", "--check"]),
                _command_check(
                    "v1.1-contract-tests",
                    [
                        python,
                        "-m",
                        "unittest",
                        "tests.test_retrieval",
                        "tests.test_drive_adapter",
                        "tests.test_issue_router",
                        "tests.test_improvement_loop",
                        "tests.test_async_auditor",
                        "tests.test_interaction_e2e",
                    ],
                ),
            ]
        )
    if version in {"1.2.0", "1.2.1", "1.3.0", "1.4.0"}:
        checks.extend(_v12_release_checks(python, workspace_root, child_quality_gates))
    e2e = _e2e_check(runs)
    interaction_e2e = _interaction_e2e_check(runs) if version in {"1.1.0", "1.2.0", "1.2.1", "1.3.0", "1.4.0"} else None
    v12_e2e = _v12_e2e_check(runs, workspace_root, child_quality_gates) if version in {"1.2.0", "1.2.1", "1.3.0", "1.4.0"} else None
    production_exchange = _production_exchange_check(
        runs,
        workspace_root,
        python,
        child_quality_gates,
        python_root,
        child_timeout_seconds,
    ) if version in {"1.3.0", "1.4.0"} else None
    initial_operations_e2e = _initial_operations_e2e_check(runs) if version == "1.4.0" else None
    live_evidence = _sandbox_live_evidence_check(github_sandbox_evidence) if version == "1.4.0" else None
    history = _history_forbidden_findings()
    passed = (
        all(item["status"] == "PASSED" for item in checks)
        and e2e["status"] == "PASSED"
        and (interaction_e2e is None or interaction_e2e["status"] == "PASSED")
        and (v12_e2e is None or v12_e2e["status"] == "PASSED")
        and (production_exchange is None or production_exchange["status"] == "PASSED")
        and (initial_operations_e2e is None or initial_operations_e2e["status"] == "PASSED")
        and (live_evidence is None or live_evidence["status"] == "PASSED")
        and history["status"] == "PASSED"
    )
    report_checks = checks + [e2e]
    if interaction_e2e is not None:
        report_checks.append(interaction_e2e)
    if v12_e2e is not None:
        report_checks.append(v12_e2e)
    if production_exchange is not None:
        report_checks.append(production_exchange)
    if initial_operations_e2e is not None:
        report_checks.append(initial_operations_e2e)
    if live_evidence is not None:
        report_checks.append(live_evidence)
    report = {
        "version": version,
        "network": "disabled",
        "status": "PASSED" if passed else "FAILED",
        "blocking": not passed,
        "checks": report_checks,
        "history": history,
        "remote_operations": [],
        "merge_operation": "NOT_PERFORMED",
        "tag_operation": "NOT_PERFORMED",
        "release_operation": "NOT_PERFORMED",
        "human_gate": "merge/release requires human approval",
    }
    if pinned_observations is not None:
        observation_provenance = [
            _observation_provenance(
                item,
                f"release-check://pinned-workspace/{item.get('repository', index)}",
            )
            for index, item in enumerate(pinned_observations)
        ]
        source_findings = [
            {
                "repository": item.get("repository"),
                "code": f"SOURCE_{item.get('source_state')}",
                "observed_commit": item.get("observed_commit"),
                "source_head": item.get("source_head"),
                "source_state": item.get("source_state"),
                **observation_provenance[index],
            }
            for index, item in enumerate(pinned_observations)
            if item.get("source_state") != "MATCHED"
        ]
        report["pinned_workspace"] = {
            "mode": "manifest-observed-commit-clone",
            "source_mutation": False,
            "repositories": pinned_observations,
            "observation_provenance": observation_provenance,
            "findings": source_findings,
        }
        report["observation_provenance"] = observation_provenance
    return report


def _pinned_workspace_failure(version: str, runs: int, error: PinnedWorkspaceError) -> dict:
    """Return a sanitized blocking report when a pin cannot be materialized."""
    observation_provenance = [
        _observation_provenance(
            item,
            f"release-check://pinned-workspace/{item.get('repository', index)}",
        )
        for index, item in enumerate(error.findings)
    ]
    return {
        "version": version,
        "network": "disabled",
        "status": "FAILED",
        "blocking": True,
        "checks": [
            {
                "id": "pinned-workspace-materialize",
                "status": "FAILED",
                "exit_code": 1,
                "reason": str(error),
                "repositories": error.findings,
            }
        ],
        "pinned_workspace": {
            "mode": "manifest-observed-commit-clone",
            "source_mutation": False,
            "repositories": error.findings,
            "findings": [
                {
                    "repository": item.get("repository"),
                    "code": "PIN_MATERIALIZATION_FAILED",
                    "observed_commit": item.get("observed_commit"),
                    "source_head": item.get("source_head"),
                    "source_state": item.get("source_state"),
                    "reason": item.get("reason"),
                    **observation_provenance[index],
                }
                for index, item in enumerate(error.findings)
            ],
            "observation_provenance": observation_provenance,
        },
        "observation_provenance": observation_provenance,
        "history": {"status": "NOT_RUN", "reason": "pin materialization failed"},
        "remote_operations": [],
        "merge_operation": "NOT_PERFORMED",
        "tag_operation": "NOT_PERFORMED",
        "release_operation": "NOT_PERFORMED",
        "human_gate": "merge/release requires human approval",
        "runs": runs,
    }


def qualify(
    version: str = "1.0.0",
    runs: int = 3,
    workspace_root: Path = V12_WORKSPACE_ROOT,
    github_sandbox_evidence: Path | None = None,
    python_root: Path | None = None,
    child_timeout_seconds: int = 60,
) -> dict:
    """Qualify using immutable child clones for every version with child gates."""
    validate_request(version, runs)
    if version not in {"1.2.0", "1.2.1", "1.3.0", "1.4.0"}:
        if python_root is None:
            return _qualify(
                version,
                runs,
                workspace_root,
                github_sandbox_evidence,
                child_timeout_seconds=child_timeout_seconds,
            )
        return _qualify(
            version,
            runs,
            workspace_root,
            github_sandbox_evidence,
            python_root=python_root,
            child_timeout_seconds=child_timeout_seconds,
        )
    manifest = load_yaml(V12_MANIFEST)
    with tempfile.TemporaryDirectory(prefix="release-pinned-workspace-") as temporary_name:
        pinned_root = Path(temporary_name)
        try:
            observations = materialize_pinned_workspace(manifest, workspace_root, pinned_root)
        except PinnedWorkspaceError as exc:
            return _pinned_workspace_failure(version, runs, exc)
        if python_root is None:
            return _qualify(
                version,
                runs,
                pinned_root,
                github_sandbox_evidence,
                observations,
                child_timeout_seconds=child_timeout_seconds,
            )
        return _qualify(
            version,
            runs,
            pinned_root,
            github_sandbox_evidence,
            observations,
            python_root=python_root,
            child_timeout_seconds=child_timeout_seconds,
        )


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
    parser = argparse.ArgumentParser(description="Qualify v1.0.0 through v1.4.0 without performing release operations")
    parser.add_argument("--version", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--workspace-root", type=Path, default=V12_WORKSPACE_ROOT)
    parser.add_argument(
        "--python-root",
        type=Path,
        help="optional root of pre-provisioned per-child environments; no installation is performed",
    )
    parser.add_argument(
        "--child-timeout",
        type=int,
        default=60,
        help="timeout in seconds for each manifest child quality gate",
    )
    parser.add_argument("--github-sandbox-evidence", type=Path, help="metadata-only evidence produced by the dedicated live sandbox lane")
    parser.add_argument("--output", type=Path, default=ROOT / "data/release-check.json")
    args = parser.parse_args()
    try:
        workspace_root = args.workspace_root if args.workspace_root.is_absolute() else Path.cwd() / args.workspace_root
        python_root = args.python_root
        if python_root is not None and not python_root.is_absolute():
            python_root = Path.cwd() / python_root
        evidence_path = args.github_sandbox_evidence
        if evidence_path is not None and not evidence_path.is_absolute():
            evidence_path = Path.cwd() / evidence_path
        result = qualify(
            args.version,
            args.runs,
            workspace_root.resolve(),
            evidence_path.resolve() if evidence_path is not None else None,
            python_root.resolve() if python_root is not None else None,
            args.child_timeout,
        )
        output = args.output if args.output.is_absolute() else Path.cwd() / args.output
        _write_atomic(output.resolve(), json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except (OSError, ReleaseCheckError, ValueError, KeyError):
        print("ERROR: release qualification could not run; remediation: inspect the declared v1 gates", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not result["blocking"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
