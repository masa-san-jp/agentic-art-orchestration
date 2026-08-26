#!/usr/bin/env python3
"""Capture a structured inspiration and settle it against the candidate pipeline."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from tools.validate import (
    load_yaml,
    validate_candidate_gates,
    validate_candidate_space,
    validate_inspiration,
    validate_retrieval_request,
    validate_retrieval_result,
    validate_selection,
)


ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._:-][a-z0-9]+)*$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9._:-]*$")
CONTRACT = "inspiration-input/v1"


class InspirationError(ValueError):
    """The inspiration cannot safely cross the interaction/pipeline boundary."""


def _error(detail: str, remediation: str) -> InspirationError:
    return InspirationError(f"inspiration: {detail}; remediation: {remediation}")


def _hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stable(value: object, name: str) -> str:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise _error(f"{name} is invalid", "use a lowercase opaque ID or code")
    return value


def _code(value: object, name: str) -> str:
    if not isinstance(value, str) or CODE_PATTERN.fullmatch(value) is None:
        raise _error(f"{name} is invalid", "use a lowercase structured code without free text")
    return value


def _snapshots(value: object, name: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise _error(f"{name} is empty", "retain at least one immutable repository@commit source")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise _error(f"{name}[{index}] is not an object", "record repository and commit metadata")
        repository = _code(item.get("repository"), f"{name}[{index}].repository")
        commit = item.get("commit")
        if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            raise _error(f"{name}[{index}].commit is invalid", "retain the complete lowercase source commit")
        if repository in seen:
            raise _error(f"{name} contains duplicate repository {repository!r}", "record one immutable commit per repository")
        seen.add(repository)
        result.append({"repository": repository, "commit": commit})
    return sorted(result, key=lambda item: item["repository"])


def _validate_retrieval(request: Mapping[str, object], retrieval: Mapping[str, object]) -> None:
    manifest = load_yaml(Path(__file__).resolve().parents[1] / "config/repositories.yaml")
    request_errors = validate_retrieval_request(dict(request), "inspiration request", manifest)
    result_errors = validate_retrieval_result(dict(retrieval), manifest, dict(request), "inspiration retrieval")
    if request_errors or result_errors:
        raise _error("retrieval provenance is invalid: " + "; ".join(request_errors + result_errors), "use the validated structured retrieval result")


def capture_inspiration(
    request: Mapping[str, object],
    retrieval: Mapping[str, object],
    *,
    run_id: str = "INSPIRATION-001:attempt-1",
    inspiration: Mapping[str, object] | None = None,
    inspiration_id: str | None = None,
    interaction_id: str | None = None,
    event_id: str | None = None,
    session_ref: str | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Capture only structured codes and immutable retrieval provenance."""
    if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise _error("run_id is invalid", "use a stable interaction execution ID")
    if not isinstance(request, Mapping) or not isinstance(retrieval, Mapping):
        raise _error("request and retrieval must be objects", "pass the validated retrieval contracts")
    _validate_retrieval(request, retrieval)
    if retrieval.get("status") in {"NO_MATCH", "BLOCKED"}:
        raise _error("cannot capture inspiration without retrieval evidence", "resolve the retrieval gap before settlement")

    supplied = dict(inspiration or {})
    unknown = sorted(set(supplied) - {"goal_code", "intent_code", "capability_codes"})
    if unknown:
        raise _error(f"structured inspiration has unsupported fields {unknown!r}", "provide codes only; do not pass raw inspiration text")

    intent_code = supplied.get("intent_code", request.get("intent_code"))
    if intent_code != request.get("intent_code"):
        raise _error("inspiration intent_code differs from retrieval request", "settle the same structured intent that was retrieved")
    capability_codes = supplied.get("capability_codes", request.get("capability_codes"))
    if capability_codes != request.get("capability_codes"):
        raise _error("inspiration capability_codes differ from retrieval request", "settle the same capability boundary that was retrieved")
    if not isinstance(capability_codes, list) or not capability_codes or any(not isinstance(item, str) for item in capability_codes):
        raise _error("capability_codes are invalid", "provide one or more structured capability codes")
    goal_code = _code(supplied.get("goal_code", "research-inspiration"), "goal_code")

    generated_at = captured_at or retrieval.get("generated_at")
    if not isinstance(generated_at, str):
        raise _error("captured_at is missing", "use the deterministic retrieval timestamp")
    source_snapshots = _snapshots(
        [{"repository": item.get("repository"), "commit": item.get("source_commit")} for item in retrieval.get("selected_repositories", [])],
        "retrieval_source_snapshots",
    )
    evidence_refs = retrieval.get("evidence")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise _error("retrieval has no evidence references", "capture only an evidenced inspiration")
    evidence_ids = sorted({item.get("evidence_id") for item in evidence_refs if isinstance(item, Mapping)})
    if not evidence_ids or any(not isinstance(item, str) or ID_PATTERN.fullmatch(item) is None for item in evidence_ids):
        raise _error("retrieval evidence IDs are invalid", "retain opaque evidence IDs only")

    digest = _hash({"run_id": run_id, "request_ref": request.get("request_id"), "goal_code": goal_code})[:16]
    generated_ids = {
        "inspiration_id": f"inspiration:{digest}",
        "interaction_id": f"interaction:inspiration:{digest}",
        "event_id": f"interaction:inspiration:{digest}:event",
        "session_ref": f"session:inspiration:{digest}",
    }
    ids = {
        key: _stable(value if value is not None else generated_ids[key], key)
        for key, value in {
            "inspiration_id": inspiration_id,
            "interaction_id": interaction_id,
            "event_id": event_id,
            "session_ref": session_ref,
        }.items()
    }
    result: dict[str, Any] = {
        "contract_version": CONTRACT,
        "inspiration_id": ids["inspiration_id"],
        "phase": "CAPTURED",
        "captured_at": generated_at,
        "capture": {
            "interaction_id": ids["interaction_id"],
            "event_id": ids["event_id"],
            "session_ref": ids["session_ref"],
            "request_ref": _stable(request.get("request_id"), "request_ref"),
            "intent": {
                "intent_code": _code(intent_code, "intent_code"),
                "capability_codes": sorted({_code(item, "capability_code") for item in capability_codes}),
                "goal_code": goal_code,
            },
        },
        "provenance": {
            "retrieval_source_snapshots": source_snapshots,
            "retrieval_evidence_refs": evidence_ids,
            "pipeline_source_snapshots": [],
        },
        "settlement": None,
        "consent": {
            "scope": str(request.get("privacy", {}).get("consent_scope", "user-requested-research")),
            "settlement_confirmed": False,
            "profile_update_permitted": False,
        },
        "privacy": {
            "raw_inspiration_stored": False,
            "raw_conversation_stored": False,
            "direct_identifiers_stored": False,
        },
    }
    errors = validate_inspiration(result)
    if errors:
        raise _error("capture violates inspiration contract: " + "; ".join(errors), "retain only structured codes and opaque references")
    return result


def _pipeline_source_snapshots(bundle: Mapping[str, object]) -> list[dict[str, str]]:
    return _snapshots(
        [{"repository": item.get("repository"), "commit": item.get("commit")} for item in bundle.get("source_repositories", [])],
        "pipeline_source_snapshots",
    )


def _candidate_input_refs(selection: Mapping[str, object]) -> list[dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    for candidate in selection.get("selected_candidates", []):
        if not isinstance(candidate, Mapping):
            continue
        inputs = candidate.get("inputs", {})
        if not isinstance(inputs, Mapping):
            continue
        for values in inputs.values():
            if not isinstance(values, list):
                continue
            for ref in values:
                if not isinstance(ref, Mapping):
                    continue
                copied = copy.deepcopy(dict(ref))
                refs[_hash(copied)] = copied
    return sorted(refs.values(), key=lambda item: (item.get("signal_id", ""), item.get("attribute", "")))


def settle_inspiration(
    capture: Mapping[str, object],
    pipeline: Mapping[str, object],
    *,
    settled_at: str | None = None,
) -> dict[str, Any]:
    """Bind a capture to a passing candidate pipeline without copying signal text."""
    captured = copy.deepcopy(dict(capture))
    capture_errors = validate_inspiration(captured)
    if capture_errors:
        raise _error("capture is invalid: " + "; ".join(capture_errors), "settle a valid CAPTURED inspiration")
    if captured.get("phase") != "CAPTURED":
        raise _error("capture is not in CAPTURED phase", "settle each inspiration exactly once")
    if not isinstance(pipeline, Mapping):
        raise _error("pipeline result must be an object", "run the validated candidate pipeline")

    candidate_space = pipeline.get("candidate_space")
    gate_report = pipeline.get("gate_report")
    selection = pipeline.get("selection")
    bundle = pipeline.get("bundle")
    pipeline_errors = []
    pipeline_errors.extend(validate_candidate_space(candidate_space, "inspiration candidate space"))
    pipeline_errors.extend(validate_candidate_gates(gate_report, "inspiration candidate gates"))
    pipeline_errors.extend(validate_selection(selection, "inspiration selection"))
    if pipeline_errors:
        raise _error("candidate pipeline is invalid: " + "; ".join(pipeline_errors), "settle only a validated candidate pipeline")
    if not isinstance(bundle, Mapping):
        raise _error("pipeline bundle is missing", "retain the normalized signal bundle provenance")
    pipeline_snapshots = _pipeline_source_snapshots(bundle)
    retrieval_snapshots = captured["provenance"]["retrieval_source_snapshots"]
    commits = {item["repository"]: item["commit"] for item in pipeline_snapshots}
    for snapshot in retrieval_snapshots:
        if commits.get(snapshot["repository"]) != snapshot["commit"]:
            raise _error(
                f"pipeline changed retrieval source {snapshot['repository']!r}",
                "settle against the same immutable source commit observed during capture",
            )
    selected_ids = [candidate.get("candidate_id") for candidate in selection.get("selected_candidates", [])]
    if not selected_ids or any(not isinstance(item, str) for item in selected_ids):
        raise _error("pipeline selected no candidate", "settle only after a gate-passing candidate is selected")
    candidate_space_hash = _hash(candidate_space)
    gate_report_hash = _hash(gate_report)
    if selection.get("candidate_space_hash") != candidate_space_hash or selection.get("gate_report_hash") != gate_report_hash:
        raise _error("selection hashes do not match pipeline artifacts", "preserve the exact candidate and gate artifacts used for selection")
    if gate_report.get("candidate_space_hash") != candidate_space.get("snapshot_id") and gate_report.get("candidate_space_hash") != candidate_space_hash:
        raise _error("gate report is not tied to the candidate space", "evaluate and settle the same candidate artifact")
    candidates_by_id = {
        candidate.get("candidate_id"): candidate
        for candidate in candidate_space.get("candidates", [])
        if isinstance(candidate, Mapping)
    }
    evaluations_by_id = {
        evaluation.get("candidate_id"): evaluation
        for evaluation in gate_report.get("evaluations", [])
        if isinstance(evaluation, Mapping)
    }
    for candidate_id in selected_ids:
        if candidate_id not in candidates_by_id:
            raise _error(f"selection references unknown candidate {candidate_id!r}", "select only candidates emitted by the pipeline")
        if evaluations_by_id.get(candidate_id, {}).get("overall_status") != "PASS":
            raise _error(f"selection references a non-passing candidate {candidate_id!r}", "settle only a candidate that passed every gate")
    for ref in _candidate_input_refs(selection):
        if commits.get(ref.get("source_repository")) != ref.get("source_commit"):
            raise _error(
                f"candidate input reference for {ref.get('signal_id')!r} is outside the pipeline snapshot",
                "preserve the source repository commit through candidate selection",
            )

    settled = copy.deepcopy(captured)
    settled["phase"] = "SETTLED"
    settled["provenance"]["pipeline_source_snapshots"] = pipeline_snapshots
    settled["provenance"]["candidate_input_refs"] = _candidate_input_refs(selection)
    settled["settlement"] = {
        "status": "SETTLED",
        "settled_at": settled_at or captured["captured_at"],
        "method": "structured-intent",
        "candidate_pipeline": "research-candidate/v1",
        "candidate_space_hash": candidate_space_hash,
        "gate_report_hash": gate_report_hash,
        "selection_hash": _hash(selection),
        "selected_candidate_ids": sorted(selected_ids),
    }
    settled["consent"]["settlement_confirmed"] = True
    errors = validate_inspiration(settled)
    if errors:
        raise _error("settlement violates inspiration contract: " + "; ".join(errors), "retain only pipeline hashes, codes, and provenance references")
    return settled


def run_inspiration_pipeline(
    request: Mapping[str, object],
    retrieval: Mapping[str, object],
    bundle: Mapping[str, object],
    *,
    run_id: str = "INSPIRATION-001:attempt-1",
    inspiration: Mapping[str, object] | None = None,
    project_id: str = "inspiration-project",
    seed_input: str = "inspiration",
) -> dict[str, Any]:
    """Capture, run the existing pipeline, and return its settled inspiration."""
    capture = capture_inspiration(request, retrieval, run_id=run_id, inspiration=inspiration)
    from tools.input_pipeline import run_input_pipeline

    return run_input_pipeline(
        dict(bundle),
        project_id=project_id,
        seed_input=seed_input,
        inspiration=capture,
    )
