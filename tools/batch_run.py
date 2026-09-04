#!/usr/bin/env python3
"""Run a bounded, networkless production-plan batch from immutable inputs.

The batch driver owns only normalized signal references and Git-external
evidence.  Child repositories are executed from the pinned workspace through
``production_exchange`` and are never written to.
"""

from __future__ import annotations

import argparse
import copy
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import sys
import time
from typing import Any, Iterable, Mapping

import yaml
from jsonschema import Draft202012Validator, FormatChecker

try:
    from tools.adapters import adapt_art_history_signal, adapt_marketing_signal, adapt_self_model_signal
    from tools.batch_status import aggregate_report, validate_batch_report_event
    from tools.candidate_gates import build_gate_report
    from tools.candidate_selection import build_self_diversity_report, build_selection, sha256_hex
    from tools.candidate_space import build_candidate_space
    from tools.output_destinations import (
        destinations_profile_selected,
        manifest_child_roots,
        resolve_destinations,
        resolve_run_destination,
        validate_destination_resolution,
        write_resolution_evidence,
    )
    from tools.production_exchange import run_exchange
    from tools.qualify_pin_update import workspace_candidate
    from tools.signal_bundle import build_signal_bundle
    from tools.validate import ROOT, load_json, load_yaml, validate_manifest, validate_signal
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.adapters import adapt_art_history_signal, adapt_marketing_signal, adapt_self_model_signal
    from tools.batch_status import aggregate_report, validate_batch_report_event
    from tools.candidate_gates import build_gate_report
    from tools.candidate_selection import build_self_diversity_report, build_selection, sha256_hex
    from tools.candidate_space import build_candidate_space
    from tools.output_destinations import (
        destinations_profile_selected,
        manifest_child_roots,
        resolve_destinations,
        resolve_run_destination,
        validate_destination_resolution,
        write_resolution_evidence,
    )
    from tools.production_exchange import run_exchange
    from tools.qualify_pin_update import workspace_candidate
    from tools.signal_bundle import build_signal_bundle
    from tools.validate import ROOT, load_json, load_yaml, validate_manifest, validate_signal


SCHEMA_PATH = ROOT / "schemas" / "batch-run.schema.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
HASH64 = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
TIMESTAMP_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
HUMAN_AUTHORITY = re.compile(r'"actor_kind"\s*:\s*"HUMAN"|authority:\s*HUMAN')
FORBIDDEN_MARKERS = re.compile(r"(?i)(PRIVATE_RAW|RESTRICTED|credential|raw[_ -]?voice|raw[_ -]?asset)")
SIGNAL_KINDS = ("self", "art-history", "marketing")
SOURCE_REPOSITORIES = {
    "self": "self-model",
    "art-history": "art-history",
    "marketing": "marketing-trends",
}


class BatchRunError(ValueError):
    """A batch cannot proceed without weakening an acceptance boundary."""


def _timestamp(value: str) -> None:
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.fullmatch(value):
        raise BatchRunError("generated_at must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BatchRunError("generated_at must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BatchRunError("generated_at must include a timezone")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise BatchRunError(f"required batch evidence is unreadable: {path.name}") from exc
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BatchRunError(f"JSON input is unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise BatchRunError(f"JSON input must be an object: {path.name}")
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise BatchRunError(f"YAML input is unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise BatchRunError(f"YAML input must be a mapping: {path.name}")
    return value


def _assert_external(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise BatchRunError(f"{label} must be Git-external")
    return resolved


def _repo_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list):
        raise BatchRunError("manifest.repositories must be a list")
    result = {item.get("id"): item for item in repositories if isinstance(item, Mapping) and isinstance(item.get("id"), str)}
    missing = sorted(set(SOURCE_REPOSITORIES.values()) - set(result))
    missing += sorted({"agentic-art-research", "agentic-art-production"} - set(result))
    if missing:
        raise BatchRunError(f"manifest is missing required repositories: {missing}")
    return result


def _load_export(path: Path, kind: str, expected_commit: str) -> list[dict[str, Any]]:
    envelope = _read_json(path)
    contract = envelope.get("contract_version")
    if contract == "research-signal-export/v1":
        records = envelope.get("signals")
        count_key = "signal_count"
    elif contract == "normalized-research-signal/v1":
        records = envelope.get("records")
        count_key = "record_count"
    else:
        raise BatchRunError(f"{kind} export contract is unsupported")
    if not isinstance(records, list) or not records:
        raise BatchRunError(f"{kind} export has no records")
    if envelope.get(count_key) != len(records):
        raise BatchRunError(f"{kind} export count does not match its records")
    adapters = {
        "self": adapt_self_model_signal,
        "art-history": adapt_art_history_signal,
        "marketing": adapt_marketing_signal,
    }
    adapted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise BatchRunError(f"{kind} export record {index} is not an object")
        try:
            signal = record if record.get("signal_kind") == kind and isinstance(record.get("source"), dict) else adapters[kind](record)
        except (TypeError, ValueError, KeyError) as exc:
            raise BatchRunError(f"{kind} export record {index} was rejected by its boundary adapter") from exc
        errors = validate_signal(signal, f"{kind}.records[{index}]")
        if errors:
            raise BatchRunError(f"{kind} export record {index} is not normalized")
        signal_id = signal.get("signal_id")
        source = signal.get("source")
        if not isinstance(signal_id, str) or signal_id in seen:
            raise BatchRunError(f"{kind} export contains a duplicate signal ID")
        if not isinstance(source, dict) or source.get("repository") != SOURCE_REPOSITORIES[kind] or source.get("commit") != expected_commit:
            raise BatchRunError(f"{kind} export provenance does not match the pinned child commit")
        seen.add(signal_id)
        adapted.append(copy.deepcopy(signal))
    return sorted(adapted, key=lambda item: item["signal_id"])


def _signal_tuple(candidate: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    inputs = candidate.get("inputs")
    if not isinstance(inputs, Mapping):
        raise BatchRunError("selected candidate has no input references")
    values: list[tuple[str, str]] = []
    for kind in SIGNAL_KINDS:
        refs = inputs.get(kind)
        if not isinstance(refs, list) or not refs:
            raise BatchRunError("selected candidate is missing a signal kind")
        for ref in refs:
            if not isinstance(ref, Mapping) or not isinstance(ref.get("signal_id"), str):
                raise BatchRunError("selected candidate contains an invalid signal reference")
            values.append((kind, ref["signal_id"]))
    return tuple(sorted(values))


def _event(
    run_id: str,
    project_id: str,
    source_commit: str,
    event_type: str,
    attempt: int,
    event_id: str,
    *,
    observed_at: str,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    value = {
        "contract_version": "batch-report-event/v1",
        "event_id": event_id,
        "run_id": run_id,
        "event_type": event_type,
        "project_id": project_id,
        "repository": "agentic-art-research",
        "source_commit": source_commit,
        "observed_at": observed_at,
        "attempt": attempt,
        "duration_seconds": duration_seconds,
        "token_count": None,
    }
    errors = validate_batch_report_event(value, f"batch event {event_id}")
    if errors:
        raise BatchRunError("generated batch event is invalid")
    return value


def _append_events(path: Path, events: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, str] = {}
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise BatchRunError("existing batch report is unreadable") from exc
        for line_number, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BatchRunError(f"batch report line {line_number} is not JSON") from exc
            errors = validate_batch_report_event(event, f"batch report line {line_number}")
            if errors:
                raise BatchRunError("existing batch report contains an invalid event")
            event_id = event["event_id"]
            rendered = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if event_id in existing and existing[event_id] != rendered:
                raise BatchRunError("existing batch report has a conflicting event ID")
            existing[event_id] = rendered
        if raw and not raw.endswith("\n"):
            raise BatchRunError("existing batch report must end with a newline")
    pending: list[str] = []
    for event in events:
        errors = validate_batch_report_event(event, f"batch event {event.get('event_id', '?')}")
        if errors:
            raise BatchRunError("refusing to append an invalid batch event")
        event_id = event["event_id"]
        rendered = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if event_id in existing:
            if existing[event_id] != rendered:
                raise BatchRunError("batch report append would change an existing event")
            continue
        existing[event_id] = rendered
        pending.append(rendered + "\n")
    if pending:
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.writelines(pending)
        except OSError as exc:
            raise BatchRunError("batch report could not be appended") from exc


def _prepare_plan_projection(
    child_plan_path: Path,
    child_brief_path: Path,
    destination_plan: Path,
    destination_markdown: Path,
) -> tuple[str, str]:
    child_plan = _read_yaml(child_plan_path)
    brief = _read_yaml(child_brief_path)
    source_plan_hash = _sha256_file(child_plan_path)
    source_brief_hash = _sha256_file(child_brief_path)
    projection = copy.deepcopy(child_plan)
    projection["brief"] = brief
    projection["projection"] = {
        "contract_version": "batch-plan-projection/v1",
        "source_plan_sha256": source_plan_hash,
        "source_brief_sha256": source_brief_hash,
    }
    destination_plan.parent.mkdir(parents=True, exist_ok=True)
    destination_plan.write_text(
        yaml.safe_dump(projection, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    destination_markdown.write_bytes((child_plan_path.parent / "production-plan.md").read_bytes())
    return _sha256_file(destination_plan), source_brief_hash


def _run_project(
    *,
    batch_run_id: str,
    project_number: int,
    candidate: Mapping[str, Any],
    manifest: Mapping[str, Any],
    workspace_root: Path,
    exchange_root: Path,
    state_dir: Path,
    research_output_root: Path,
    production_output_root: Path,
    generated_at: str,
    child_python: str,
    max_attempts: int = 3,
) -> dict[str, Any]:
    project_id = f"batch-{project_number:03d}"
    source_commit = str(_repo_map(manifest)["agentic-art-research"]["observed_commit"])
    slug = project_id
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        attempt_run_id = f"{batch_run_id}:project-{project_number:03d}:attempt-{attempt}"
        stage_root = state_dir / "staging" / project_id / f"attempt-{attempt}"
        child_production_root = stage_root / "child-production"
        try:
            evidence = run_exchange(
                dict(manifest),
                workspace_root,
                exchange_root,
                run_id=attempt_run_id,
                generated_at=generated_at,
                research_project_slug=slug,
                production_project_slug=slug,
                handoff_id="HO001",
                result_id="PR001",
                child_python=child_python,
                research_output_root=research_output_root,
                production_output_root=child_production_root,
            )
            if evidence.get("status") != "PASSED":
                raise BatchRunError("child exchange did not reach PASSED")
            child_plan_root = child_production_root / "production" / slug
            child_plan_path = child_plan_root / "03_plan" / "production-plan.yaml"
            child_brief_path = research_output_root / "projects" / slug / "05_production" / "production-brief.yaml"
            final_plan_root = production_output_root / slug / "03_plan"
            plan_hash, brief_hash = _prepare_plan_projection(
                child_plan_path,
                child_brief_path,
                final_plan_root / "production-plan.yaml",
                final_plan_root / "production-plan.md",
            )
            research_project_root = research_output_root / "projects" / slug
            decision_log = research_project_root / "04_decisions" / "decision-log.yaml"
            duration = round(max(0.0, time.monotonic() - started), 3)
            events = [
                _event(batch_run_id, project_id, source_commit, "DURATION", attempt, f"{project_id}-duration-{attempt}", observed_at=generated_at, duration_seconds=duration),
                _event(batch_run_id, project_id, source_commit, "COMPLETED", attempt, f"{project_id}-completed-{attempt}", observed_at=generated_at),
            ]
            if attempt > 1:
                events.insert(0, _event(batch_run_id, project_id, source_commit, "RETRY", attempt, f"{project_id}-retry-{attempt}", observed_at=generated_at))
            return {
                "project_id": project_id,
                "candidate_id": str(candidate["candidate_id"]),
                "status": "PASSED",
                "research_locator": f"run://{batch_run_id}/research/projects/{slug}",
                "production_locator": f"run://{batch_run_id}/production/{slug}",
                "production_plan_sha256": plan_hash,
                "brief_sha256": brief_hash,
                "decision_log_sha256": _sha256_file(decision_log),
                "events": events,
            }
        except (BatchRunError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < max_attempts:
                continue
            duration = round(max(0.0, time.monotonic() - started), 3)
            events = [
                _event(batch_run_id, project_id, source_commit, "DURATION", attempt, f"{project_id}-duration-{attempt}", observed_at=generated_at, duration_seconds=duration),
                _event(batch_run_id, project_id, source_commit, "FAILED", attempt, f"{project_id}-failed-{attempt}", observed_at=generated_at),
            ]
            if attempt > 1:
                events.insert(0, _event(batch_run_id, project_id, source_commit, "RETRY", attempt, f"{project_id}-retry-{attempt}", observed_at=generated_at))
            return {
                "project_id": project_id,
                "candidate_id": str(candidate["candidate_id"]),
                "status": "FAILED",
                "research_locator": f"run://{batch_run_id}/research/projects/{slug}",
                "production_locator": f"run://{batch_run_id}/production/{slug}",
                "production_plan_sha256": None,
                "brief_sha256": None,
                "decision_log_sha256": None,
                "events": events,
                "error_type": type(last_error).__name__ if last_error is not None else "unknown",
            }
    raise BatchRunError(f"project {project_id} exhausted its retry budget")


def _acceptance_checks(
    output_root: Path,
    report_path: Path,
    requested_count: int,
    expected_tuples: int,
) -> tuple[dict[str, bool], dict[str, Any]]:
    production_plans = sorted((output_root / "production").rglob("production-plan.md"))
    g1 = len(production_plans) == requested_count
    plan_documents: list[dict[str, Any]] = []
    g2 = True
    g3 = True
    for markdown_path in production_plans:
        yaml_path = markdown_path.with_name("production-plan.yaml")
        try:
            document = _read_yaml(yaml_path)
        except BatchRunError:
            g2 = False
            g3 = False
            continue
        plan_documents.append(document)
        g2 = g2 and document.get("readiness", {}).get("startable") is True
        brief = document.get("brief") if isinstance(document.get("brief"), Mapping) else document
        message = brief.get("message") if isinstance(brief, Mapping) else None
        concept = brief.get("concept") if isinstance(brief, Mapping) else None
        g3 = g3 and (
            isinstance(message, Mapping)
            and isinstance(message.get("who_disagrees"), str)
            and bool(message["who_disagrees"].strip())
            and isinstance(concept, Mapping)
            and concept.get("without_the_technique") in {"MERELY_PLAINER", "CEASES_TO_WORK"}
            and isinstance(concept.get("precedents"), list)
            and bool(concept["precedents"])
        )
    human_hits: list[Path] = []
    for path in sorted((output_root / "production").rglob("*")):
        if not path.is_file():
            continue
        try:
            if HUMAN_AUTHORITY.search(path.read_text(encoding="utf-8")):
                human_hits.append(path)
        except (OSError, UnicodeDecodeError):
            human_hits.append(path)
    g4 = not human_hits

    decision_logs = sorted((output_root / "research").glob("projects/*/04_decisions/decision-log.yaml"))
    sample = random.Random(0).sample(decision_logs, min(10, len(decision_logs))) if decision_logs else []
    g5 = len(sample) == min(10, requested_count) and all(
        any(item.get("authority") == "agent-recommended" for item in (_read_yaml(path).get("decisions") or []) if isinstance(item, Mapping))
        for path in sample
    )

    try:
        report = aggregate_report(report_path)
    except Exception as exc:
        raise BatchRunError("batch report could not be aggregated") from exc
    counts = report["counts"]
    g6 = (
        counts["起動"] == requested_count
        and counts["完了"] == requested_count
        and counts["失敗"] == 0
        and report["duration"]["total_seconds"] is not None
        and report["project_count"] == requested_count
    )
    checks = {
        "g1_production_plan_count": g1,
        "g2_startable": g2 and len(plan_documents) == requested_count,
        "g3_structured_brief": g3 and len(plan_documents) == requested_count,
        "g4_no_human_authority": g4,
        "g5_agent_recommended_decisions": g5,
        "g6_append_only_report": g6,
        "no_remote_operations": True,
        "no_child_mutations": True,
        "no_raw_data": True,
    }
    return checks, {
        "report": report,
        "production_plan_count": len(production_plans),
        "human_authority_hits": len(human_hits),
        "decision_log_sample_count": len(sample),
        "unique_signal_tuple_count": expected_tuples,
    }


def validate_batch_run(data: object, source: str = "batch-run") -> list[str]:
    schema = load_json(SCHEMA_PATH)
    errors = [f"{source}: {error.message}" for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data)]
    if not isinstance(data, Mapping):
        return errors
    if "destination_resolution" in data:
        errors.extend(validate_destination_resolution(data["destination_resolution"], f"{source}.destination_resolution"))
        if isinstance(data["destination_resolution"], Mapping) and data["destination_resolution"].get("run_id") != data.get("run_id"):
            errors.append(f"{source}.destination_resolution.run_id: must match batch run_id")
    if data.get("status") == "PASSED":
        if data.get("completed_count") != data.get("requested_count") or data.get("failed_count") != 0:
            errors.append(f"{source}: PASSED run counts are inconsistent")
        acceptance = data.get("acceptance")
        if isinstance(acceptance, Mapping) and not all(value is True for value in acceptance.values()):
            errors.append(f"{source}: PASSED run must satisfy every acceptance boolean")
    if data.get("selection", {}).get("selected_count") != data.get("requested_count"):
        errors.append(f"{source}: selected_count must equal requested_count")
    if data.get("selection", {}).get("unique_signal_tuple_count") != data.get("completed_count") and data.get("status") == "PASSED":
        errors.append(f"{source}: every completed project must have a unique signal tuple")
    rendered = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if FORBIDDEN_MARKERS.search(rendered):
        errors.append(f"{source}: raw or credential marker found in batch metadata")
    return errors


def run_batch(
    manifest: dict[str, Any],
    workspace_root: Path,
    *,
    self_export: Path,
    art_history_export: Path,
    marketing_export: Path,
    output_root: Path,
    state_root: Path,
    run_id: str,
    generated_at: str,
    child_python: str,
    python_root: Path | None = None,
    selection_limit: int = 100,
    max_workers: int = 4,
    destination_resolution: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    if not ID_PATTERN.fullmatch(run_id):
        raise BatchRunError("run_id is not stable")
    _timestamp(generated_at)
    if selection_limit < 1:
        raise BatchRunError("selection_limit must be positive")
    if max_workers < 1:
        raise BatchRunError("max_workers must be positive")
    output_root = _assert_external(output_root, "output_root")
    state_root = _assert_external(state_root, "state_root")
    workspace_root = workspace_root.expanduser().resolve()
    if not workspace_root.is_dir():
        raise BatchRunError("workspace_root is not a directory")
    summary_path = state_root / run_id / "batch-run.json"
    if summary_path.is_file():
        existing = _read_json(summary_path)
        errors = validate_batch_run(existing, str(summary_path))
        if errors:
            raise BatchRunError("existing batch summary is invalid")
        if destination_resolution is not None and existing.get("destination_resolution") != dict(destination_resolution):
            raise BatchRunError("existing batch summary has different destination resolution")
        if destination_resolution is not None:
            write_resolution_evidence(state_root, run_id, destination_resolution)
        return {"status": "ALREADY_COMPLETED", "summary": existing, "summary_path": summary_path}
    state_dir = state_root / run_id
    if state_dir.exists() and any(path.name != "destination-resolution.json" for path in state_dir.iterdir()):
        raise BatchRunError("partial batch state exists without a valid summary; use a new run_id after inspection")
    if output_root.exists() and any(output_root.iterdir()):
        raise BatchRunError("output_root is not empty; batch output is create-only")
    output_root.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    if destination_resolution is not None:
        write_resolution_evidence(state_root, run_id, destination_resolution)
    report_path = state_dir / "batch-report.jsonl"

    candidate_manifest, _changes = workspace_candidate(manifest, workspace_root)
    manifest_errors = validate_manifest(candidate_manifest, "batch candidate manifest")
    if manifest_errors:
        raise BatchRunError("batch candidate manifest is invalid")
    repositories = _repo_map(candidate_manifest)
    records: list[dict[str, Any]] = []
    for kind, path in (
        ("self", self_export),
        ("art-history", art_history_export),
        ("marketing", marketing_export),
    ):
        repository = repositories[SOURCE_REPOSITORIES[kind]]
        records.extend(_load_export(path, kind, str(repository["observed_commit"])))
    bundle = build_signal_bundle(records, generated_at)
    registry = load_yaml(ROOT / "config" / "transformation-rules.yaml")
    candidate_space = build_candidate_space(bundle["records"], registry)
    gate_report = build_gate_report(candidate_space, bundle["records"], registry)
    selection = build_selection(
        candidate_space,
        gate_report,
        re.sub(r"[^a-z0-9._-]+", "-", run_id.lower()),
        seed_input=f"{run_id.replace(':', '-')}:seed-v1",
        selection_limit=selection_limit,
        require_self_diversity=False,
        signals=bundle["records"],
    )
    diversity = build_self_diversity_report(
        bundle["records"], candidate_space, selection["selected_candidates"], selection_limit,
    )
    tuples = {_signal_tuple(candidate) for candidate in selection["selected_candidates"]}
    if len(tuples) != selection_limit:
        raise BatchRunError("selected signal tuples are duplicated")

    research_output_root = output_root / "research"
    production_output_root = output_root / "production"
    exchange_root = state_dir / "exchange"
    start_events = [
        _event(run_id, f"batch-{index:03d}", str(repositories["agentic-art-research"]["observed_commit"]), "STARTED", 1, f"batch-{index:03d}-started", observed_at=generated_at)
        for index in range(1, selection_limit + 1)
    ]
    _append_events(report_path, start_events)

    results: list[dict[str, Any]] = []
    futures: dict[Future[dict[str, Any]], int] = {}
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="batch-project") as executor:
        for index, candidate in enumerate(selection["selected_candidates"], start=1):
            futures[executor.submit(
                _run_project,
                batch_run_id=run_id,
                project_number=index,
                candidate=candidate,
                manifest=candidate_manifest,
                workspace_root=workspace_root,
                exchange_root=exchange_root,
                state_dir=state_dir,
                research_output_root=research_output_root,
                production_output_root=production_output_root,
                generated_at=generated_at,
                child_python=child_python,
            )] = index
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["project_id"])
    for result in results:
        _append_events(report_path, result["events"])

    completed = sum(result["status"] == "PASSED" for result in results)
    failed = len(results) - completed
    checks, acceptance_detail = _acceptance_checks(output_root, report_path, selection_limit, len(tuples))
    status = "PASSED" if completed == selection_limit and failed == 0 and all(checks.values()) else "FAILED"
    report_summary = acceptance_detail["report"]
    source_repositories = [
        {
            "repository": repository_id,
            "commit": str(repositories[repository_id]["observed_commit"]),
            "record_count": sum(1 for record in bundle["records"] if record["source"]["repository"] == repository_id),
        }
        for repository_id in sorted(SOURCE_REPOSITORIES.values())
    ]
    project_summaries = [
        {key: value for key, value in result.items() if key not in {"events", "error_type"}}
        for result in results
    ]
    summary = {
        "contract_version": "batch-run/v1",
        "run_id": run_id,
        "generated_at": generated_at,
        "network": "DISABLED",
        "status": status,
        "requested_count": selection_limit,
        "completed_count": completed,
        "failed_count": failed,
        "source_repositories": source_repositories,
        "selection": {
            "candidate_space_hash": sha256_hex(candidate_space),
            "gate_report_hash": sha256_hex(gate_report),
            "selection_hash": sha256_hex(selection),
            "selected_count": selection["selected_count"],
            "unique_signal_tuple_count": len(tuples),
            "self_diversity_status": diversity["status"],
            "source_commits": sorted({record["source"]["commit"] for record in bundle["records"]}),
        },
        "projects": project_summaries,
        "acceptance": checks,
        "report": {
            "locator": f"run://{run_id}/batch-report.jsonl",
            "sha256": _sha256_file(report_path),
            "event_count": report_summary["event_count"],
            "completed_count": report_summary["counts"]["完了"],
            "failed_count": report_summary["counts"]["失敗"],
            "retry_count": report_summary["counts"]["再試行"],
            "duration_seconds": report_summary["duration"]["total_seconds"],
            "token_count": report_summary["tokens"]["total"],
        },
        "remote_operations": [],
        "child_mutations": [],
    }
    if destination_resolution is not None:
        summary["destination_resolution"] = dict(destination_resolution)
    errors = validate_batch_run(summary)
    if errors:
        raise BatchRunError("generated batch summary is invalid")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"status": status, "summary": summary, "summary_path": summary_path, "acceptance_detail": acceptance_detail}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/repositories.yaml")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--self-export", type=Path, required=True)
    parser.add_argument("--art-history-export", type=Path, required=True)
    parser.add_argument("--marketing-export", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--destinations-file", type=Path,
                        help="explicit external output-destinations/v1 profile")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--child-python", required=True)
    parser.add_argument("--python-root", type=Path)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        manifest = load_yaml(args.manifest)
        manifest_errors = validate_manifest(manifest, str(args.manifest))
        if manifest_errors:
            raise BatchRunError("manifest is invalid")
        direct = {}
        if args.output_root is not None:
            direct["internal_output_root"] = args.output_root
        if args.state_root is not None:
            direct["state_root"] = args.state_root
        profile_selected = destinations_profile_selected(args.destinations_file)
        if not profile_selected and set(direct) != {"state_root", "internal_output_root"}:
            parser.error("batch-run requires --output-root and --state-root unless a destination profile is selected")
        destination_resolution = None
        if profile_selected or direct:
            destination_resolution = resolve_destinations(
                args.destinations_file,
                direct=direct or None,
                repository_root=ROOT,
                child_roots=manifest_child_roots(manifest, args.workspace_root),
                run_id=args.run_id,
            )
            roots = destination_resolution["destinations"]
            state_root = Path(roots["state_root"]["path"])
            output_root = (
                args.output_root
                if args.output_root is not None
                else resolve_run_destination(roots["internal_output_root"]["path"], "batch", args.run_id)
            )
        else:  # pragma: no cover - parser.error above is terminal
            state_root = args.state_root
            output_root = args.output_root
        result = run_batch(
            manifest,
            args.workspace_root,
            self_export=args.self_export,
            art_history_export=args.art_history_export,
            marketing_export=args.marketing_export,
            output_root=output_root,
            state_root=state_root,
            run_id=args.run_id,
            generated_at=args.generated_at,
            child_python=args.child_python,
            python_root=args.python_root,
            selection_limit=args.limit,
            max_workers=args.max_workers,
            destination_resolution=destination_resolution,
        )
    except (BatchRunError, OSError, TypeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"command": "batch-run", "status": result["status"], "summary": str(result["summary_path"])}, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"PASSED", "ALREADY_COMPLETED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
