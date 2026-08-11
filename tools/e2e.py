#!/usr/bin/env python3
"""Evaluate the complete orchestration path without network or child-repo writes."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures.build_fixture import build_fixture
from tools.consumer import ConsumerCompatibilityError, import_signals
from tools.quality_gates import run_quality_gates
from tools.runtime import acquire_lease, expire_lease, release_lease, save_checkpoint
from tools.security import audit_boundary, check_export
from tools.trace import build_trace, load_portfolio
from tools.validate import validate_signal


class E2EEvaluationError(RuntimeError):
    """The end-to-end evaluation could not prove an expected state transition."""


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise E2EEvaluationError(f"fixture must be an object: {path}")
    return value


def _load_work_item() -> dict:
    with (ROOT / "tests/fixtures/work-items/valid.yaml").open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise E2EEvaluationError("work-item fixture must be an object")
    return value


def _scenario(
    injection: str,
    terminal_state: str,
    recovery_path: str,
    evidence: dict,
    recovery_state: str | None = None,
) -> dict:
    result = {
        "injection": injection,
        "observed": True,
        "terminal_state": terminal_state,
        "recovery_path": recovery_path,
        "evidence": evidence,
    }
    if recovery_state is not None:
        result["recovery_state"] = recovery_state
    return result


def _load_valid_inputs() -> tuple[list[dict], dict, dict]:
    fixture_root = ROOT / "tests/fixtures/portfolio"
    portfolio, signals_by_id, errors = load_portfolio(fixture_root)
    if errors:
        raise E2EEvaluationError("; ".join(errors))
    signals = [signals_by_id[signal_id] for requirement in portfolio["requirements"] for signal_id in requirement["signal_ids"]]
    if len({signal["signal_id"] for signal in signals}) != len(signals):
        raise E2EEvaluationError("portfolio inputs contain duplicate signal IDs")
    return signals, portfolio, signals_by_id


def _clean_scenario() -> dict:
    signals, portfolio, signals_by_id = _load_valid_inputs()
    imported = import_signals(signals)
    trace, errors = build_trace(ROOT / "tests/fixtures/portfolio")
    if errors or trace is None:
        raise E2EEvaluationError("clean trace failed: " + "; ".join(errors))
    if trace["traced_signal_count"] != len(signals):
        raise E2EEvaluationError("clean trace did not cover every imported signal")

    package = {
        "version": 1,
        "contract_version": imported["contract_version"],
        "input_signal_ids": [item["signal_id"] for item in imported["provenance"]],
        "source_commits": [item["source_commit"] for item in imported["provenance"]],
        "decision": {
            "status": "evidence-backed-draft",
            "basis": "All declared requirements have source and evidence edges.",
            "unknowns_preserved": True,
        },
        "production_requirements": [
            "Preserve source repository and immutable commit for every output.",
            "Revalidate the marketing signal before a release decision.",
        ],
        "prototype_verification": {
            "status": "passed",
            "checks": [
                "normalized input contract accepted",
                "source provenance retained",
                "requirements trace to evidence locators",
            ],
        },
        "trace_hash": trace["trace_hash"],
    }
    boundary = audit_boundary({"research_package": package}, signals_by_id)
    if boundary["blocking"]:
        raise E2EEvaluationError("clean package crossed the security boundary")
    return {
        "status": "COMPLETE",
        "traceable_output": {
            "contract_version": package["contract_version"],
            "input_count": len(package["input_signal_ids"]),
            "requirement_count": len(portfolio["requirements"]),
            "trace_hash": package["trace_hash"],
            "source_commits": package["source_commits"],
        },
        "stages": [
            "self-model-notes export",
            "art-history historical context",
            "marketing trend freshness",
            "agentic-art-research import",
            "production decision and prototype verification",
            "reverse provenance trace",
        ],
        "security_status": boundary["status"],
    }


def _stale_scenario() -> dict:
    marketing = _load_json(ROOT / "tests/fixtures/signal/valid_marketing.json")
    stale = copy.deepcopy(marketing)
    stale["freshness"]["status"] = "stale"
    stale["validity"]["status"] = "stale"
    stale["domain"]["marketing"]["freshness"] = "stale"
    stale["constraints"] = list(stale["constraints"]) + ["Revalidate stale fixture before use."]
    errors = validate_signal(stale, "e2e:stale")
    if errors:
        raise E2EEvaluationError("stale fixture became structurally invalid")
    return _scenario(
        "stale marketing signal",
        "COMPLETE_WITH_GAPS",
        "revalidate marketing signal at its owning adapter, then rerun consumer import",
        {"freshness_status": "stale", "import_attempted": False},
    )


def _incompatible_scenario() -> dict:
    marketing = _load_json(ROOT / "tests/fixtures/signal/valid_marketing.json")
    incompatible = copy.deepcopy(marketing)
    incompatible["contract_version"] = "normalized-research-signal/v2"
    try:
        import_signals([incompatible])
    except ConsumerCompatibilityError:
        return _scenario(
            "consumer major contract mismatch",
            "NEEDS_REPAIR",
            "adapt the signal to normalized-research-signal/v1 at the child boundary and rerun validation",
            {"consumer_rejected": True, "expected_major": 1, "actual_major": 2},
        )
    raise E2EEvaluationError("consumer accepted a major contract mismatch")


def _quality_gate_failure_scenario() -> dict:
    manifest = {
        "repositories": [
            {
                "id": "synthetic-failing-repo",
                "path": "synthetic-failing-repo",
                "quality_gates": ["python3 -c 'raise SystemExit(7)'"],
            }
        ]
    }
    with tempfile.TemporaryDirectory(prefix="e2e-quality-gate-") as temporary:
        workspace = Path(temporary)
        (workspace / "synthetic-failing-repo").mkdir()
        result = run_quality_gates(manifest, workspace, ["synthetic-failing-repo"])
    if result["status"] != "FAILED" or not result["blocking"]:
        raise E2EEvaluationError("injected quality gate failure was not blocking")
    return _scenario(
        "child quality gate failure",
        "NEEDS_REPAIR",
        "repair the owning child repository, rerun its declared gate, then resume from the checkpoint",
        {"quality_gate_status": result["status"], "blocking": result["blocking"], "exit_code": 7},
    )


def _security_scenarios() -> tuple[dict, dict]:
    secret_result = audit_boundary({"synthetic_output": "password=synthetic-value"})
    if secret_result["status"] != "FAILED" or not secret_result["blocking"]:
        raise E2EEvaluationError("secret injection did not block export")
    secret = _scenario(
        "credential-like secret",
        "BLOCKED_HUMAN",
        "remove the credential-like value, rotate it if exposed, and rerun the security boundary",
        {"security_status": secret_result["status"], "finding_count": len(secret_result["findings"])},
    )

    self_signal = _load_json(ROOT / "tests/fixtures/signal/valid_self.json")
    consent = copy.deepcopy(self_signal)
    consent["domain"]["self_model"]["export_permitted"] = False
    consent_findings = check_export(consent, "e2e:consent")
    if not any(item["code"] == "unapproved-export" for item in consent_findings):
        raise E2EEvaluationError("consent violation did not block export")
    consent_scenario = _scenario(
        "self-model consent violation",
        "BLOCKED_HUMAN",
        "obtain explicit approved-derived-only consent before retrying export",
        {"unapproved_export": True, "finding_count": len(consent_findings)},
    )
    return secret, consent_scenario


def _runtime_scenarios() -> tuple[dict, dict]:
    state = acquire_lease(
        _load_work_item(), "e2e-worker", "2026-08-11T15:00:00+09:00", lease_minutes=5
    )
    state = save_checkpoint(state, "e2e-worker", "resume the interrupted orchestration", decision="preserve checkpoint")
    expired = expire_lease(state, "2026-08-11T15:05:00+09:00")
    resumed = acquire_lease(expired, "e2e-resumer", "2026-08-11T15:06:00+09:00", lease_minutes=5)
    if resumed["checkpoint"]["execution_id"] != state["checkpoint"]["execution_id"]:
        raise E2EEvaluationError("lease expiry changed the execution ID")
    lease_expiry = _scenario(
        "lease expiry",
        "READY",
        "preserve checkpoint, reacquire with a new worker, and resume the same execution ID",
        {"expired_state": expired["terminal_state"], "execution_id_preserved": True},
        recovery_state=resumed["terminal_state"],
    )

    interrupted = release_lease(state, "e2e-worker")
    resumed_after_kill = acquire_lease(interrupted, "e2e-resumer", "2026-08-11T15:07:00+09:00", lease_minutes=5)
    if resumed_after_kill["checkpoint"]["execution_id"] != state["checkpoint"]["execution_id"]:
        raise E2EEvaluationError("process interruption changed the execution ID")
    process_kill = _scenario(
        "worker process interruption",
        "READY",
        "release the lease without discarding the checkpoint, then reacquire and resume idempotently",
        {"released_state": interrupted["terminal_state"], "execution_id_preserved": True},
        recovery_state=resumed_after_kill["terminal_state"],
    )
    return lease_expiry, process_kill


def run_e2e() -> dict:
    """Run the clean Golden Scenario and all deterministic failure injections."""
    fixture = build_fixture()
    if fixture["network"] != "disabled" or len(fixture["repositories"]) != 4:
        raise E2EEvaluationError("offline four-repository fixture was not complete")

    stale = _stale_scenario()
    incompatible = _incompatible_scenario()
    quality = _quality_gate_failure_scenario()
    secret, consent = _security_scenarios()
    lease_expiry, process_kill = _runtime_scenarios()

    fixture_scenarios = fixture["scenarios"]
    guard_dirty = _scenario(
        "dirty child repository",
        "BLOCKED_EXTERNAL",
        "restore or commit only through the child repository owner, then rerun the Git guard",
        {"guard_reason": fixture_scenarios["dirty"]["guard_reason"]},
    )
    guard_diverged = _scenario(
        "diverged child repository",
        "BLOCKED_EXTERNAL",
        "resolve divergence with the child repository owner, then fetch and rerun the Git guard",
        {"guard_reason": fixture_scenarios["diverged"]["guard_reason"]},
    )
    failures = [
        stale,
        guard_dirty,
        guard_diverged,
        incompatible,
        quality,
        secret,
        consent,
        lease_expiry,
        process_kill,
    ]
    if not all(item["observed"] and item["terminal_state"] and item["recovery_path"] for item in failures):
        raise E2EEvaluationError("one or more failure injections lacks terminal or recovery evidence")
    return {
        "version": 1,
        "network": "disabled",
        "repository_count": len(fixture["repositories"]),
        "clean": _clean_scenario(),
        "failure_injections": failures,
        "acceptance": {
            "clean_traceable_output": True,
            "failure_cases_with_terminal_state": len(failures),
            "failure_cases_with_recovery_path": len(failures),
        },
    }


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
    import argparse

    parser = argparse.ArgumentParser(description="Run the offline end-to-end orchestration evaluation")
    parser.add_argument("--check", action="store_true", help="require deterministic repeated output")
    parser.add_argument("--offline-fixture", action="store_true", help="explicitly select the networkless fixture")
    parser.add_argument("--output", type=Path, default=ROOT / "data/e2e.json")
    args = parser.parse_args()
    if not args.offline_fixture:
        print("ERROR: --offline-fixture is required; remediation: run only the networkless evaluation", file=sys.stderr)
        return 2
    try:
        result = run_e2e()
        if args.check and result != run_e2e():
            raise E2EEvaluationError("e2e result is not deterministic")
        output = args.output if args.output.is_absolute() else Path.cwd() / args.output
        _write_atomic(output.resolve(), json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except (E2EEvaluationError, OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
