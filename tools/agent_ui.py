#!/usr/bin/env python3
"""Compose the bounded initial Codex/Claude Code interaction profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.drive_live_bridge import DriveLiveBridge, FakeDriveLiveProvider, GoogleDriveProvider
from tools.github_issue_adapter import FixtureProvider, GithubApiProvider, deliver
from tools.input_pipeline import run_input_pipeline
from tools.inspiration import capture_inspiration
from tools.issue_router import route_feedback
from tools.retrieval import route_query
from tools.startup import build_startup_report
from tools.validate import load_json, load_yaml, validate_agent_ui_result


DEFAULT_OUTPUT = ROOT / "data/agent-ui.json"
DEFAULT_FIXTURE_ROOT = Path(tempfile.gettempdir()) / "agentic-art-orchestration-agent-ui"
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"


class AgentUIError(ValueError):
    """The initial interaction cannot remain inside its declared boundaries."""


def _error(detail: str, remediation: str) -> AgentUIError:
    return AgentUIError(f"agent ui: {detail}; remediation: {remediation}")


def _hash(value: object) -> str:
    if isinstance(value, bytes):
        payload = value
    else:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load(path: Path) -> object:
    try:
        return load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise _error(f"cannot read structured input {path.name}", "supply a valid metadata-only JSON contract") from exc


def _source_snapshots(retrieval: Mapping[str, object]) -> list[dict]:
    return [
        {"repository": item["repository"], "commit": item["source_commit"]}
        for item in retrieval["selected_repositories"]
    ]


def _answer_context(retrieval: Mapping[str, object]) -> dict:
    evidence_by_repository: dict[str, list[dict]] = {}
    for evidence in retrieval["evidence"]:
        evidence_by_repository.setdefault(evidence["repository"], []).append(evidence)
    sources = []
    for selected in retrieval["selected_repositories"]:
        repository = selected["repository"]
        evidence = evidence_by_repository.get(repository, [])
        sources.append(
            {
                "repository": repository,
                "commit": selected["source_commit"],
                "repository_at_commit": f"{repository}@{selected['source_commit']}",
                "freshness": sorted({item["freshness_status"] for item in evidence}) or ["unknown"],
                "evidence_ids": sorted(item["evidence_id"] for item in evidence),
            }
        )
    return {
        "retrieval_status": retrieval["status"],
        "sources": sources,
        "gaps": sorted(retrieval["unknowns"]),
        "constraints": sorted(retrieval["domain_constraints"]),
    }


def _artifact_metadata(run_id: str, retrieval: Mapping[str, object], feedback_ids: list[str]) -> dict:
    source_snapshots = _source_snapshots(retrieval)
    artifact_suffix = _hash(run_id)[:12]
    interaction_id = f"interaction:agent-ui:{artifact_suffix}"
    return {
        "artifact_id": f"artifact:agent-ui:{artifact_suffix}",
        "mime_type": "application/vnd.google-apps.document",
        "category": "document",
        "created_at": retrieval["generated_at"],
        "creator": {"agent_id": "agent-ui", "version": "1.0.0"},
        "interaction_id": interaction_id,
        "source_snapshots": source_snapshots,
        "evidence_refs": sorted(item["evidence_id"] for item in retrieval["evidence"]),
        "access": {"scope": "private", "consent_scope": "user-requested-output"},
        "retention": {"policy": "keep", "review_at": None},
        "lineage": {"derived_from": [], "supersedes": []},
        "feedback_refs": sorted(feedback_ids),
    }


def _artifact_summary(result: dict | None, requested: bool) -> dict:
    if not requested:
        return {
            "requested": False,
            "status": "NOT_REQUESTED",
            "operation": "NONE",
            "artifact_id": None,
            "provider_file_id": None,
            "content_hash": None,
            "source_snapshots": [],
        }
    artifact = result.get("artifact") if isinstance(result, dict) else None
    return {
        "requested": True,
        "status": {"PLANNED": "PLANNED", "CREATED": "CREATED", "REPLAYED": "REPLAYED", "BLOCKED": "BLOCKED"}.get(result.get("status") if result else "BLOCKED", "BLOCKED"),
        "operation": {"NONE": "PLAN", "CREATE": "CREATE", "REPLAY": "REPLAY"}.get(result.get("operation") if result else "NONE", "NONE"),
        "artifact_id": artifact.get("artifact_id") if isinstance(artifact, Mapping) else None,
        "provider_file_id": artifact.get("provider_file_id") if isinstance(artifact, Mapping) else None,
        "content_hash": result.get("content_hash") if isinstance(result, Mapping) else None,
        "source_snapshots": artifact.get("source_snapshots", []) if isinstance(artifact, Mapping) else [],
    }


def _feedback_summary(routing: Mapping[str, object], delivery: Mapping[str, object]) -> dict:
    routes = routing["routes"]
    candidates = [route["issue_candidate"] for route in routes if isinstance(route.get("issue_candidate"), Mapping)]
    records = [
        {
            "deduplication_key": record["deduplication_key"],
            "target_repository": record["target_repository"],
            "status": record["status"],
            "operation": record["operation"],
        }
        for record in delivery["records"]
    ]
    return {
        "captured_ids": sorted(routing["input_feedback_ids"]),
        "explicit_ids": sorted(route["feedback_id"] for route in routes if route["kind"] not in {"inferred_friction", "inferred_need"}),
        "inferred_ids": sorted(route["feedback_id"] for route in routes if route["kind"] in {"inferred_friction", "inferred_need"}),
        "routing_statuses": sorted({route["routing_status"] for route in routes}),
        "issue_candidate_count": len(candidates),
        "issue_delivery_status": delivery["status"],
        "issue_records": records,
    }


def _remote_summary(artifact_result: Mapping[str, object] | None, delivery: Mapping[str, object]) -> list[dict]:
    operations: list[dict] = []
    if artifact_result and artifact_result.get("mode") == "LIVE":
        operations.extend({"operation": item["operation"], "system": "google-drive"} for item in artifact_result.get("remote_operations", []))
    if delivery.get("mode") == "LIVE":
        operations.extend(
            {"operation": item["operation"], "system": "github"}
            for item in delivery.get("remote_operations", [])
            if item.get("operation") in {"READ", "CREATE", "REUSE"}
        )
    unique = sorted({tuple(sorted(item.items())) for item in operations})
    return [dict(item) for item in unique]


def _inspiration_summary(settled: Mapping[str, object] | None) -> dict:
    if not isinstance(settled, Mapping):
        return {
            "status": "NOT_REQUESTED",
            "inspiration_id": None,
            "capture_ref": None,
            "settlement_ref": None,
            "intent": None,
            "candidate_space_hash": None,
            "gate_report_hash": None,
            "selection_hash": None,
            "selected_candidate_ids": [],
            "retrieval_source_snapshots": [],
            "pipeline_source_snapshots": [],
            "candidate_input_refs": [],
            "privacy": {
                "raw_inspiration_stored": False,
                "raw_conversation_stored": False,
                "direct_identifiers_stored": False,
            },
        }
    inspiration_id = settled["inspiration_id"]
    settlement = settled["settlement"]
    return {
        "status": "SETTLED",
        "inspiration_id": inspiration_id,
        "capture_ref": f"inspiration:capture:{inspiration_id}",
        "settlement_ref": f"inspiration:settlement:{inspiration_id}",
        "intent": settled["capture"]["intent"],
        "candidate_space_hash": settlement["candidate_space_hash"],
        "gate_report_hash": settlement["gate_report_hash"],
        "selection_hash": settlement["selection_hash"],
        "selected_candidate_ids": settlement["selected_candidate_ids"],
        "retrieval_source_snapshots": settled["provenance"]["retrieval_source_snapshots"],
        "pipeline_source_snapshots": settled["provenance"]["pipeline_source_snapshots"],
        "candidate_input_refs": settled["provenance"]["candidate_input_refs"],
        "privacy": settled["privacy"],
    }


def run_agent_ui(
    *,
    request: Mapping[str, object],
    index: Mapping[str, object],
    feedback: list[Mapping[str, object]],
    run_id: str = "AGENT-UI-001:attempt-1",
    agent_client: str = "Codex",
    offline_fixture: bool = False,
    fixture_root: Path = DEFAULT_FIXTURE_ROOT,
    artifact_mode: str = "plan",
    issue_mode: str = "plan",
    confirm_drive: bool = False,
    confirm_issue: bool = False,
    artifact_content: str | bytes = "synthetic agent UI output; content remains outside the evidence envelope",
    inspiration: Mapping[str, object] | None = None,
    signal_bundle: Mapping[str, object] | None = None,
) -> dict:
    if not isinstance(run_id, str) or re.fullmatch(ID_PATTERN, run_id) is None:
        raise _error("run_id is invalid", "use a stable interaction execution ID")
    if agent_client not in {"Codex", "Claude Code"}:
        raise _error("agent client is unsupported", "choose Codex or Claude Code")
    if artifact_mode not in {"none", "plan", "live"} or issue_mode not in {"plan", "live"}:
        raise _error("operation mode is invalid", "use artifact none/plan/live and issue plan/live")
    if artifact_mode == "live" and issue_mode == "live":
        raise _error("Drive and Issue live operations cannot be combined", "run one explicitly confirmed external CREATE lane at a time")
    manifest = load_yaml(ROOT / "config/repositories.yaml")
    startup = build_startup_report(manifest, offline_fixture=offline_fixture, fixture_root=fixture_root, run_id=f"{run_id}:startup", agent_client=agent_client)
    if (artifact_mode == "live" or issue_mode == "live") and startup["status"] != "READY" and not offline_fixture:
        raise _error("external CREATE requires a clean READY startup", "resolve startup findings and keep the interaction read-only")
    retrieval = route_query(request, index, manifest, f"{run_id}:retrieval")
    settled_inspiration = None
    if inspiration is not None:
        if signal_bundle is None:
            raise _error("inspiration requires a normalized signal bundle", "pass the validated bundle to reach the candidate pipeline")
        capture = capture_inspiration(request, retrieval, run_id=run_id, inspiration=inspiration)
        pipeline = run_input_pipeline(
            dict(signal_bundle),
            project_id="inspiration-project",
            seed_input="inspiration",
            inspiration=capture,
        )
        settled_inspiration = pipeline["inspiration"]
    routing = route_feedback(list(feedback), manifest, f"{run_id}:feedback")
    candidates = [route["issue_candidate"] for route in routing["routes"] if isinstance(route.get("issue_candidate"), Mapping)]
    issue_provider = None
    if issue_mode == "live":
        if not confirm_issue:
            raise _error("live Issue mode requires confirmation", "pass confirm_issue=True only after the target allowlist is reviewed")
        issue_provider = FixtureProvider() if offline_fixture else GithubApiProvider(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "")
    delivery = deliver(candidates, manifest, mode="live" if issue_mode == "live" else "plan", provider=issue_provider, run_id=f"{run_id}:issues") if candidates else {
        "status": "BLOCKED",
        "mode": "LIVE" if issue_mode == "live" else "PLAN",
        "records": [],
        "remote_operations": [],
    }

    artifact_result = None
    if artifact_mode != "none":
        metadata = _artifact_metadata(run_id, retrieval, sorted(routing["input_feedback_ids"]))
        if artifact_mode == "live":
            if not confirm_drive:
                raise _error("live Drive mode requires confirmation", "pass confirm_drive=True only after the approved folder and retention are reviewed")
            provider = FakeDriveLiveProvider() if offline_fixture else GoogleDriveProvider(os.environ.get("AGENTIC_ART_GOOGLE_DRIVE_TOKEN", ""))
            artifact_result = DriveLiveBridge(provider).create(
                content=artifact_content,
                metadata=metadata,
                idempotency_key=f"{run_id}:artifact",
                mode="live",
                folder_id=None if not offline_fixture else "fixture-drive-live-sandbox",
                run_id=f"{run_id}:drive",
                confirm_live=True,
            )
        else:
            artifact_result = DriveLiveBridge().create(
                content=artifact_content,
                metadata=metadata,
                idempotency_key=f"{run_id}:artifact",
                mode="plan",
                run_id=f"{run_id}:drive",
            )

    status = startup["status"]
    artifact_summary = _artifact_summary(artifact_result, artifact_mode != "none")
    result = {
        "contract_version": "agent-ui/v1",
        "run_id": run_id,
        "agent_client": agent_client,
        "status": status,
        "startup": {
            "status": startup["status"],
            "parent_commit": startup["parent_commit"],
            "finding_codes": sorted(item["code"] for item in startup["findings"]),
            "capabilities": sorted(item["capability"] for item in startup["capabilities"] if item["status"] != "BLOCKED"),
        },
        "answer": _answer_context(retrieval),
        "artifact": artifact_summary,
        "feedback": _feedback_summary(routing, delivery),
        "inspiration": _inspiration_summary(settled_inspiration),
        "privacy": {
            "raw_query_stored": False,
            "raw_conversation_stored": False,
            "drive_content_stored": False,
            "credentials_stored": False,
            "direct_identifiers_stored": False,
        },
        "remote_operations": _remote_summary(artifact_result, delivery),
    }
    errors = validate_agent_ui_result(result)
    if errors:
        raise _error("result violates agent UI contract: " + "; ".join(errors), "retain only metadata and opaque references")
    return result


def _write_or_check(result: dict, output: Path, check: bool) -> None:
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            raise _error("agent UI output is missing or stale", "run without --check to materialize the deterministic result")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded Codex/Claude Code initial interaction profile")
    parser.add_argument("--request", type=Path, default=ROOT / "tests/fixtures/retrieval/valid_art.json")
    parser.add_argument("--index", type=Path, default=ROOT / "tests/fixtures/retrieval/index.json")
    parser.add_argument("--feedback", action="append", type=Path, default=[])
    parser.add_argument("--run-id", default="AGENT-UI-001:attempt-1")
    parser.add_argument("--agent-client", choices=["Codex", "Claude Code"], default="Codex")
    parser.add_argument("--offline-fixture", action="store_true")
    parser.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    parser.add_argument("--artifact-mode", choices=["none", "plan", "live"], default="plan")
    parser.add_argument("--issue-mode", choices=["plan", "live"], default="plan")
    parser.add_argument("--confirm-drive", action="store_true")
    parser.add_argument("--confirm-issue", action="store_true")
    parser.add_argument("--artifact-content-file", type=Path)
    parser.add_argument("--inspiration", type=Path, help="structured inspiration codes; raw text is not accepted")
    parser.add_argument("--signal-bundle", type=Path, help="normalized signal bundle used by the candidate pipeline")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        feedback_paths = args.feedback or [ROOT / "tests/fixtures/feedback/valid_explicit.json", ROOT / "tests/fixtures/feedback/valid_inferred.json"]
        artifact_content: str | bytes = "synthetic agent UI output; content remains outside the evidence envelope"
        if args.artifact_content_file:
            artifact_content = args.artifact_content_file.read_bytes()
        inspiration = _load(args.inspiration) if args.inspiration else None
        signal_bundle = _load(args.signal_bundle) if args.signal_bundle else None
        if inspiration is not None and signal_bundle is None:
            raise _error("--signal-bundle is required with --inspiration", "pass a validated normalized signal bundle")
        result = run_agent_ui(
            request=_load(args.request),
            index=_load(args.index),
            feedback=[_load(path) for path in feedback_paths],
            run_id=args.run_id,
            agent_client=args.agent_client,
            offline_fixture=args.offline_fixture,
            fixture_root=args.fixture_root.resolve(),
            artifact_mode=args.artifact_mode,
            issue_mode=args.issue_mode,
            confirm_drive=args.confirm_drive,
            confirm_issue=args.confirm_issue,
            artifact_content=artifact_content,
            inspiration=inspiration,
            signal_bundle=signal_bundle,
        )
        _write_or_check(result, args.output.resolve(), args.check)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"command": "agent-ui", "changed": not args.check, "status": result["status"], "retrieval_status": result["answer"]["retrieval_status"], "artifact_status": result["artifact"]["status"], "issue_delivery_status": result["feedback"]["issue_delivery_status"]}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
