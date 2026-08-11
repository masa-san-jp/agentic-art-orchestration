#!/usr/bin/env python3
"""Run the v1.1 interaction and continuous-improvement loop without network writes."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.async_auditor import build_async_audit
from tools.drive_adapter import DriveArtifactAdapter, FakeDrive
from tools.improvement_loop import build_improvement_loop
from tools.issue_router import route_feedback
from tools.retrieval import route_query
from tools.runtime import acquire_lease, expire_lease, release_lease, save_checkpoint
from tools.security import audit_boundary
from tools.validate import (
    load_yaml,
    validate_external_artifact,
    validate_interaction_e2e,
    validate_interaction_event,
)


class InteractionE2EError(RuntimeError):
    """The v1.1 networkless scenario did not prove a required transition."""


def _load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(microsecond=0)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _path(relative: str) -> Path:
    return ROOT / relative


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
        raise InteractionE2EError(f"cannot observe parent commit: {exc}") from exc
    commit = completed.stdout.strip()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise InteractionE2EError("parent HEAD is not a complete lowercase commit")
    return commit


def _source_snapshots(retrieval_result: Mapping[str, object]) -> list[dict]:
    return [
        {"repository": item["repository"], "commit": item["source_commit"]}
        for item in retrieval_result["selected_repositories"]
    ]


def _feedback_signals(artifact_id: str, interaction_id: str, event_id: str) -> list[dict]:
    explicit = copy.deepcopy(_load_json(_path("tests/fixtures/feedback/valid_explicit.json")))
    inferred = copy.deepcopy(_load_json(_path("tests/fixtures/feedback/valid_inferred.json")))
    for signal in (explicit, inferred):
        signal["source"] = {
            "interaction_id": interaction_id,
            "event_id": event_id,
            "artifact_refs": [artifact_id],
        }
        signal["observed_at"] = "2026-08-11T12:01:00Z"
    return [explicit, inferred]


def _interaction_event(
    source_snapshots: list[dict],
    evidence_ids: list[str],
    artifact_id: str,
    feedback_ids: list[str],
    interaction_id: str,
    event_id: str,
    occurred_at: str,
) -> dict:
    event = copy.deepcopy(_load_json(_path("tests/fixtures/interactions/valid.json")))
    event.update(
        {
            "interaction_id": interaction_id,
            "event_id": event_id,
            "occurred_at": occurred_at,
            "session_ref": "session:interaction-e2e",
            "source_snapshots": source_snapshots,
            "signal_refs": evidence_ids,
            "explicit_feedback_refs": feedback_ids,
        }
    )
    event["outcome"]["artifact_refs"] = [artifact_id]
    event["outcome"]["unresolved_codes"] = ["retrieval-evidence-gap"]
    return event


def _recovery_proof() -> dict:
    work_item = _load_yaml(_path("tests/fixtures/work-items/valid.yaml"))
    active = acquire_lease(work_item, "interaction-e2e-agent", "2026-08-11T12:00:00Z", lease_minutes=5)
    checkpointed = save_checkpoint(
        active,
        "interaction-e2e-agent",
        "resume the interaction backstage lane",
        decision="preserve the interaction checkpoint",
    )
    expired = expire_lease(checkpointed, "2026-08-11T12:05:00Z")
    resumed_after_expiry = acquire_lease(expired, "interaction-e2e-resumer", "2026-08-11T12:06:00Z", lease_minutes=5)
    released = release_lease(checkpointed, "interaction-e2e-agent")
    resumed_after_interrupt = acquire_lease(released, "interaction-e2e-resumer", "2026-08-11T12:07:00Z", lease_minutes=5)
    execution_id = active["checkpoint"]["execution_id"]
    if resumed_after_expiry["checkpoint"]["execution_id"] != execution_id or resumed_after_interrupt["checkpoint"]["execution_id"] != execution_id:
        raise InteractionE2EError("runtime recovery changed the execution ID")
    return {
        "lease_expiry_recovered": expired["terminal_state"] == "READY" and resumed_after_expiry["terminal_state"] == "IN_PROGRESS",
        "process_interruption_recovered": released["terminal_state"] == "READY" and resumed_after_interrupt["terminal_state"] == "IN_PROGRESS",
        "execution_id_preserved": True,
    }


def run_interaction_e2e(run_id: str = "INTERACTION-E2E-001:attempt-1") -> dict:
    """Run retrieval, artifact, feedback, improvement, recovery, and audit as one scenario."""
    manifest = load_yaml(_path("config/repositories.yaml"))
    request = _load_json(_path("tests/fixtures/retrieval/valid_art.json"))
    index = _load_json(_path("tests/fixtures/retrieval/index.json"))
    retrieval_result = route_query(request, index, manifest, f"{run_id}:retrieval")
    generated_at = retrieval_result["generated_at"]
    source_snapshots = _source_snapshots(retrieval_result)
    evidence_ids = [item["evidence_id"] for item in retrieval_result["evidence"]]
    interaction_id = "interaction:e2e:001"
    event_id = "interaction:e2e:001:event:001"
    artifact_id = "artifact:interaction-e2e:001"
    feedback_ids = ["feedback:interaction-001:002", "feedback:interaction-001:001"]

    metadata = {
        "artifact_id": artifact_id,
        "mime_type": "application/vnd.google-apps.document",
        "category": "document",
        "created_at": generated_at,
        "creator": {"agent_id": "interaction-agent", "version": "1.1.0"},
        "interaction_id": interaction_id,
        "source_snapshots": source_snapshots,
        "evidence_refs": evidence_ids,
        "access": {"scope": "private", "consent_scope": "user-requested-output"},
        "retention": {"policy": "keep", "review_at": None},
        "lineage": {"derived_from": [], "supersedes": []},
        "feedback_refs": feedback_ids,
    }
    drive = FakeDrive()
    adapter = DriveArtifactAdapter(drive)
    user_output_bytes = b"synthetic interaction output stays in the external fake Drive"
    created = adapter.create_artifact(
        content=user_output_bytes,
        metadata=metadata,
        idempotency_key=f"{run_id}:artifact-create",
    )
    replay = adapter.create_artifact(
        content=user_output_bytes,
        metadata=metadata,
        idempotency_key=f"{run_id}:artifact-create",
    )
    artifact = created["artifact"]
    if created["created"] is not True or replay["operation"] != "REPLAY" or drive.file_count() != 1 or len(drive.operations) != 1:
        raise InteractionE2EError("append-only artifact create/idempotency proof failed")
    if drive.read_content(artifact["provider_file_id"]) != user_output_bytes:
        raise InteractionE2EError("fake Drive did not retain the external output bytes")
    if validate_external_artifact(artifact, "interaction-e2e artifact"):
        raise InteractionE2EError("created artifact envelope failed validation")

    signals = _feedback_signals(artifact_id, interaction_id, event_id)
    event = _interaction_event(source_snapshots, evidence_ids, artifact_id, [item["feedback_id"] for item in signals if item["kind"] in {"explicit_request", "explicit_dissatisfaction", "output_correction", "knowledge_gap"}], interaction_id, event_id, generated_at)
    event_errors = validate_interaction_event(event, "interaction-e2e event")
    if event_errors:
        raise InteractionE2EError("\n".join(event_errors))
    routed = route_feedback(signals, manifest, f"{run_id}:routing")
    execution = _load_json(_path("tests/fixtures/improvement/execution.json"))
    parent_commit = _parent_commit()
    improvement = build_improvement_loop(routed, execution, manifest, f"{run_id}:improvement", parent_commit=parent_commit)
    recovery = _recovery_proof()

    audit_report = _load_json(_path("data/audit.json"))
    snapshot = _load_json(_path("data/snapshot.json"))
    captured_at = _parse_timestamp(snapshot["captured_at"])
    audit_lease = {
        "lane": "ASYNC_AUDIT",
        "status": "held",
        "owner": "interaction-e2e-auditor",
        "execution_id": f"{run_id}:audit",
        "expires_at": _timestamp(captured_at + timedelta(minutes=45)),
    }
    asynchronous_audit = build_async_audit(
        audit_report,
        snapshot,
        audit_lease,
        user_artifacts=[{
            "artifact_id": artifact["artifact_id"],
            "provider_file_id": artifact["provider_file_id"],
            "content_hash": artifact["content_hash"],
        }],
        parent_commit=parent_commit,
        run_id=f"{run_id}:audit",
    )

    artifact_summary = {
        "artifact_id": artifact["artifact_id"],
        "provider_file_id": artifact["provider_file_id"],
        "operation": artifact["operation"],
        "content_hash": artifact["content_hash"],
        "source_snapshots": artifact["source_snapshots"],
        "evidence_refs": artifact["evidence_refs"],
    }
    result = {
        "contract_version": "interaction-e2e/v1",
        "run_id": run_id,
        "generated_at": generated_at,
        "network": "disabled",
        "interaction_blocking": False,
        "user_artifact_policy": "CREATE_ONLY",
        "retrieval": {
            "status": retrieval_result["status"],
            "selected_repositories": [item["repository"] for item in retrieval_result["selected_repositories"]],
            "source_snapshots": source_snapshots,
            "evidence_ids": evidence_ids,
            "unknowns": retrieval_result["unknowns"],
        },
        "artifact": artifact_summary,
        "interaction": {
            "interaction_id": event["interaction_id"],
            "event_id": event["event_id"],
            "artifact_refs": event["outcome"]["artifact_refs"],
            "source_snapshots": event["source_snapshots"],
            "raw_conversation_stored": event["privacy"]["raw_conversation_stored"],
            "direct_identifiers_stored": event["privacy"]["direct_identifiers_stored"],
        },
        "feedback": {
            "feedback_ids": sorted(item["feedback_id"] for item in signals),
            "inferred_feedback_ids": sorted(item["feedback_id"] for item in signals if item["kind"] in {"inferred_friction", "inferred_need"}),
            "promoted_to_user_fact": False,
        },
        "routing": {
            "route_count": len(routed["routes"]),
            "statuses": sorted({route["routing_status"] for route in routed["routes"]}),
            "duplicate_suppression_count": len(routed["duplicate_suppressions"]),
            "issue_operations": routed["issue_operations"],
        },
        "improvement": {
            "outcome_count": len(improvement["outcomes"]),
            "statuses": sorted({outcome["delivery_status"] for outcome in improvement["outcomes"]}),
            "draft_pr_plan_count": len(improvement["draft_pr_plans"]),
            "remote_operations": improvement["remote_operations"],
        },
        "recovery": recovery,
        "audit": {
            "lane": asynchronous_audit["lane"],
            "interaction_blocking": asynchronous_audit["interaction_blocking"],
            "proposal_count": len(asynchronous_audit["proposals"]),
            "artifact_operations": asynchronous_audit["artifact_operations"],
        },
        "security": {"status": "PASSED", "blocking": False},
        "acceptance": {
            "retrieval_versioned": retrieval_result["contract_version"] == "retrieval-result/v1",
            "artifact_immutable": created["created"] and replay["operation"] == "REPLAY" and len(drive.operations) == 1,
            "feedback_captured": len(signals) == 2,
            "issue_routed": len(routed["routes"]) == len(signals),
            "improvement_checkpointed": bool(improvement["outcomes"]),
            "audit_independent": asynchronous_audit["lane"] == "ASYNC_AUDIT" and asynchronous_audit["interaction_blocking"] is False,
            "no_remote_mutation": not routed["issue_operations"] and not improvement["remote_operations"] and not asynchronous_audit["artifact_operations"],
        },
        "remote_operations": [],
    }
    security = audit_boundary({"interaction-e2e": result})
    result["security"] = {"status": security["status"], "blocking": security["blocking"]}
    errors = validate_interaction_e2e(result, manifest, "interaction-e2e result")
    if errors:
        raise InteractionE2EError("\n".join(errors))
    if security["status"] != "PASSED":
        raise InteractionE2EError("interaction E2E result crossed the security boundary")
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
    parser = argparse.ArgumentParser(description="Run the networkless v1.1 interaction and improvement E2E")
    parser.add_argument("--run-id", default="INTERACTION-E2E-001:attempt-1")
    parser.add_argument("--output", type=Path, default=ROOT / "data/interaction-e2e.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = run_interaction_e2e(args.run_id)
        content = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        output_path = args.output.resolve()
        if args.check:
            if not output_path.is_file():
                raise InteractionE2EError("interaction E2E output is missing; remediation: run without --check to materialize interaction-e2e.json")
            if output_path.read_text(encoding="utf-8") != content:
                raise InteractionE2EError("interaction E2E output is stale; remediation: rerun without --check")
        else:
            _write_atomic(output_path, content)
    except (InteractionE2EError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"command": "interaction-e2e", "changed": not args.check, "network": result["network"], "draft_pr_plan_count": result["improvement"]["draft_pr_plan_count"], "remote_operation_count": len(result["remote_operations"])}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
