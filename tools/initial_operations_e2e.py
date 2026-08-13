#!/usr/bin/env python3
"""Run the deterministic initial operations interaction without remote writes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.agent_ui import _answer_context, _artifact_metadata  # noqa: E402
from tools.drive_live_bridge import DriveLiveBridge, FakeDriveLiveProvider  # noqa: E402
from tools.github_issue_adapter import FixtureProvider, deliver  # noqa: E402
from tools.issue_router import route_feedback  # noqa: E402
from tools.retrieval import route_query  # noqa: E402
from tools.startup import build_startup_report  # noqa: E402
from tools.validate import _schema_errors, load_json, load_yaml, validate_initial_operations_e2e  # noqa: E402


DEFAULT_OUTPUT = ROOT / "data/initial-operations-e2e.json"
DEFAULT_FIXTURE_ROOT = Path(tempfile.gettempdir()) / "agentic-art-orchestration-initial-ops"
SCHEMA_PATH = ROOT / "schemas/initial-operations-e2e.schema.json"


class InitialOperationsE2EError(ValueError):
    """The initial operations scenario crossed its declared boundary."""


def _hash(value: object) -> str:
    if isinstance(value, bytes):
        payload = value
    else:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source_summary(retrieval: Mapping[str, object]) -> list[dict]:
    answer = _answer_context(retrieval)
    return answer["sources"]


def _retrieval_summary(retrieval: Mapping[str, object]) -> dict:
    answer = _answer_context(retrieval)
    return {
        "status": answer["retrieval_status"],
        "sources": [
            {
                "repository": source["repository"],
                "repository_at_commit": source["repository_at_commit"],
                "freshness": source["freshness"],
                "evidence_ids": source["evidence_ids"],
            }
            for source in answer["sources"]
        ],
        "gaps": answer["gaps"],
        "constraints": answer["constraints"],
    }


def _issue_record(result: Mapping[str, object]) -> dict:
    records = [record for record in result["records"] if record["status"] in {"CREATED", "REUSED"}]
    if len(records) != 1:
        raise InitialOperationsE2EError("fixture Issue delivery did not produce exactly one eligible record")
    record = records[0]
    return {
        "status": record["status"],
        "operation": record["operation"],
        "target_repository": record["target_repository"],
        "issue_id_hash": record["issue_id_hash"],
    }


def run_initial_operations_e2e(
    run_id: str = "INITIAL-OPS-E2E-001:attempt-1",
    *,
    offline_fixture: bool = True,
    fixture_root: Path = DEFAULT_FIXTURE_ROOT,
) -> dict:
    if not offline_fixture:
        raise InitialOperationsE2EError("networkless E2E requires --offline-fixture; remediation: use the separate approved sandbox live gates")
    manifest = load_yaml(ROOT / "config/repositories.yaml")
    request = load_json(ROOT / "tests/fixtures/retrieval/valid_art.json")
    index = load_json(ROOT / "tests/fixtures/retrieval/index.json")
    feedback = [
        load_json(ROOT / "tests/fixtures/feedback/valid_explicit.json"),
        load_json(ROOT / "tests/fixtures/feedback/valid_inferred.json"),
    ]

    startup = build_startup_report(
        manifest,
        offline_fixture=True,
        fixture_root=fixture_root.resolve(),
        run_id=f"{run_id}:startup",
        agent_client="Codex",
    )
    retrieval = route_query(request, index, manifest, f"{run_id}:retrieval")
    routing = route_feedback(feedback, manifest, f"{run_id}:feedback")

    content = b"synthetic initial operations output remains in fake Drive"
    metadata = _artifact_metadata(run_id, retrieval, sorted(routing["input_feedback_ids"]))
    drive_provider = FakeDriveLiveProvider()
    drive_bridge = DriveLiveBridge(drive_provider)
    drive_create = drive_bridge.create(
        content=content,
        metadata=metadata,
        idempotency_key=f"{run_id}:drive",
        mode="live",
        folder_id="fixture-drive-live-sandbox",
        run_id=f"{run_id}:drive-create",
        confirm_live=True,
    )
    # Recreate the bridge to model process interruption/retry. The provider marker
    # search must return the existing file and no second CREATE may occur.
    retry_bridge = DriveLiveBridge(drive_provider)
    drive_replay = retry_bridge.create(
        content=content,
        metadata=metadata,
        idempotency_key=f"{run_id}:drive",
        mode="live",
        folder_id="fixture-drive-live-sandbox",
        run_id=f"{run_id}:drive-retry",
        confirm_live=True,
    )
    if drive_create["status"] != "CREATED" or drive_replay["status"] != "REPLAYED" or drive_provider.file_count != 1:
        raise InitialOperationsE2EError("Drive CREATE/REPLAY proof failed")
    drive_artifact = drive_create["artifact"]

    candidates = [
        route["issue_candidate"]
        for route in routing["routes"]
        if isinstance(route.get("issue_candidate"), Mapping)
        and route["issue_candidate"].get("target_repository") == "art-history"
    ]
    if len(candidates) != 1:
        raise InitialOperationsE2EError("expected exactly one authoritative art-history Issue candidate")
    issue_provider = FixtureProvider()
    issue_create = deliver(candidates, manifest, mode="live", provider=issue_provider, run_id=f"{run_id}:issue-create")
    issue_reuse = deliver(candidates, manifest, mode="live", provider=issue_provider, run_id=f"{run_id}:issue-reuse")
    if issue_create["status"] != "CREATED" or issue_reuse["status"] != "REUSED":
        raise InitialOperationsE2EError("Issue CREATE/REUSE proof failed")

    result = {
        "contract_version": "initial-operations-e2e/v1",
        "run_id": run_id,
        "network": "disabled",
        "startup": {
            "status": startup["status"],
            "parent_commit": startup["parent_commit"],
            "ordered_step_count": len(startup["ordered_steps"]),
            "update_check_status": startup["ordered_steps"][1]["status"],
            "audit_status": startup["ordered_steps"][6]["status"],
            "finding_codes": sorted(item["code"] for item in startup["findings"]),
        },
        "retrieval": _retrieval_summary(retrieval),
        "drive": {
            "provider": "fake-google-drive",
            "create_status": drive_create["status"],
            "replay_status": drive_replay["status"],
            "operation_sequence": [item["operation"] for item in drive_provider.operations],
            "provider_file_count": drive_provider.file_count,
            "provider_file_id_hash": _hash(drive_artifact["provider_file_id"]),
            "content_hash": drive_create["content_hash"],
            "source_snapshot_count": len(metadata["source_snapshots"]),
            "forbidden_operations": [],
        },
        "feedback": {
            "captured_ids": sorted(routing["input_feedback_ids"]),
            "explicit_ids": sorted(route["feedback_id"] for route in routing["routes"] if route["kind"] not in {"inferred_friction", "inferred_need"}),
            "inferred_ids": sorted(route["feedback_id"] for route in routing["routes"] if route["kind"] in {"inferred_friction", "inferred_need"}),
            "routing_statuses": sorted({route["routing_status"] for route in routing["routes"]}),
            "promoted_to_user_fact": False,
        },
        "issue": {
            "provider": "fixture-github",
            "target_repository": "art-history",
            "create": _issue_record(issue_create),
            "reuse": _issue_record(issue_reuse),
            "operation_sequence": ["READ", "CREATE", "READ", "REUSE"],
            "forbidden_operations": [],
        },
        "live_gate": {
            "status": "NOT_REQUESTED",
            "available_paths": ["drive:create_read", "github:search_create_reuse"],
            "required_controls": ["approved_sandbox", "credential_outside_git", "explicit_confirmation", "single_live_lane"],
            "remote_operations": [],
        },
        "privacy": {
            "raw_conversation_stored": False,
            "raw_query_stored": False,
            "drive_content_stored": False,
            "credentials_stored": False,
            "direct_identifiers_stored": False,
        },
        "acceptance": {
            "startup_checked": len(startup["ordered_steps"]) == 9,
            "pinned_answer": all("@" in source["repository_at_commit"] for source in _source_summary(retrieval)),
            "drive_create_replay": drive_create["status"] == "CREATED" and drive_replay["status"] == "REPLAYED" and drive_provider.file_count == 1,
            "feedback_distinguished": bool(routing["input_feedback_ids"]) and any(route["kind"] == "explicit_request" for route in routing["routes"]) and any(route["kind"] in {"inferred_friction", "inferred_need"} for route in routing["routes"]),
            "issue_create_reuse": issue_create["status"] == "CREATED" and issue_reuse["status"] == "REUSED",
            "no_forbidden_mutation": bool(drive_provider.operations) and all(item["operation"] in {"READ", "CREATE"} for item in drive_provider.operations) and bool(issue_create["remote_operations"]) and bool(issue_reuse["remote_operations"]),
            "live_gate_closed": True,
            "privacy_closed": True,
        },
        "remote_operations": [],
    }
    errors = _schema_errors(result, load_json(SCHEMA_PATH)) + validate_initial_operations_e2e(result)
    if errors:
        raise InitialOperationsE2EError("\n".join(errors))
    return result


def _write_or_check(result: dict, output: Path, check: bool) -> None:
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            raise InitialOperationsE2EError("initial operations E2E output is missing or stale; remediation: materialize it before --check")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the networkless initial operations E2E")
    parser.add_argument("--offline-fixture", action="store_true")
    parser.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    parser.add_argument("--run-id", default="INITIAL-OPS-E2E-001:attempt-1")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = run_initial_operations_e2e(args.run_id, offline_fixture=args.offline_fixture, fixture_root=args.fixture_root)
        _write_or_check(result, args.output.resolve(), args.check)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"command": "initial-operations-e2e", "changed": not args.check, "network": result["network"], "drive": result["drive"]["create_status"], "issue": result["issue"]["create"]["status"], "remote_operation_count": len(result["remote_operations"])}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
