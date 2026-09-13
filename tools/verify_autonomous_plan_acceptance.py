#!/usr/bin/env python3
"""Verify AP-06's external-agent acceptance manifest by inspecting its evidence.

The manifest is an index, not a success assertion.  This verifier hashes every
referenced file, checks the delivery and owner records, counts questions and
forbidden operations from the operation trace, and compares the manifest with a
separate provider execution record.  It therefore cannot turn a JSON field
such as ``status=COMPLETED`` into evidence by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/autonomous-plan-acceptance.schema.json"
SHA256_LENGTH = 64
SHA40_LENGTH = 40
REQUIRED_OWNERS = {
    "self-model-notes",
    "art-history-notes",
    "marketing-trends-notes",
    "agentic-art-research",
    "agentic-art-production",
    "viewer-response-notes",
    "agentic-art-project",
    "agentic-art-orchestration",
}
MODES = ("resume", "new-clone", "fork")
QUESTION_KINDS = {"human_question", "approval_request", "user_prompt"}
FORBIDDEN_OPERATIONS = {
    "merge",
    "release",
    "public_share",
    "consent_expansion",
    "destructive_git",
    "external_cost_over_declared_budget",
    "physical_action",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _absolute_file(value: Any, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value.startswith("/"):
        errors.append(f"{label}: evidence path must be absolute")
        return None
    path = Path(value)
    if path.is_symlink():
        errors.append(f"{label}: symlink evidence path is not accepted")
        return None
    if not path.is_file():
        errors.append(f"{label}: evidence file is unavailable")
        return None
    return path


def _verify_hash(path: Path | None, expected: Any, label: str, errors: list[str]) -> str | None:
    if path is None:
        return None
    if not isinstance(expected, str) or len(expected) != SHA256_LENGTH:
        errors.append(f"{label}: expected sha256 is malformed")
        return None
    observed = _sha256(path)
    if observed != expected:
        errors.append(f"{label}: sha256 mismatch")
        return None
    return observed


def _load_json_ref(item: Mapping[str, Any], path_key: str, hash_key: str, label: str, errors: list[str]) -> dict[str, Any] | None:
    path = _absolute_file(item.get(path_key), f"{label}.{path_key}", errors)
    if _verify_hash(path, item.get(hash_key), f"{label}.{hash_key}", errors) is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path is not None else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        errors.append(f"{label}: evidence is not valid UTF-8 JSON")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label}: evidence must be a JSON object")
        return None
    return value


def _schema_errors(manifest: Any) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return ["jsonschema is unavailable; install the locked repository environment"]
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"manifest schema cannot be read: {exc}"]
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for item in sorted(validator.iter_errors(manifest), key=lambda error: list(error.path)):
        location = ".".join(str(part) for part in item.path) or "manifest"
        errors.append(f"{location}: {item.message}")
    return errors


def _artifact_hashes(run: Mapping[str, Any], errors: list[str]) -> dict[str, str]:
    observed: dict[str, str] = {}
    artifacts = run.get("artifacts", [])
    for index, artifact in enumerate(artifacts):
        label = f"run[{run.get('run_id')}].artifacts[{index}]"
        if not isinstance(artifact, Mapping):
            errors.append(f"{label}: artifact must be an object")
            continue
        path = _absolute_file(artifact.get("path"), f"{label}.path", errors)
        digest = _verify_hash(path, artifact.get("sha256"), f"{label}.sha256", errors)
        if digest is not None:
            observed[str(artifact.get("kind"))] = digest
    if "plan" not in observed:
        errors.append(f"run[{run.get('run_id')}]: a hashed plan artifact is required")
    return observed


def _verify_provider_execution(
    manifest: Mapping[str, Any], run: Mapping[str, Any], plan_hash: str | None, errors: list[str]
) -> None:
    ref = run.get("provider_execution")
    if not isinstance(ref, Mapping):
        errors.append(f"run[{run.get('run_id')}]: provider execution evidence is missing")
        return
    evidence = _load_json_ref(ref, "evidence_path", "evidence_sha256", f"run[{run.get('run_id')}].provider_execution", errors)
    if evidence is None:
        return
    provider = manifest.get("provider", {})
    identity = run.get("identity", {})
    if evidence.get("contract_version") != "provider-execution-evidence/v1":
        errors.append(f"run[{run.get('run_id')}].provider_execution: wrong execution evidence contract")
    for key, expected in (("run_id", run.get("run_id")), ("mode", run.get("mode")), ("provider_type", provider.get("type")), ("model", provider.get("model"))):
        if evidence.get(key) != expected:
            errors.append(f"run[{run.get('run_id')}].provider_execution: observed {key} does not match the manifest")
    if evidence.get("external_agent") is not True:
        errors.append(f"run[{run.get('run_id')}].provider_execution: external-agent execution is not observed")
    if evidence.get("synthetic_identity") != identity.get("synthetic"):
        errors.append(f"run[{run.get('run_id')}].provider_execution: identity classification does not match the run")
    if evidence.get("identity") != identity:
        errors.append(f"run[{run.get('run_id')}].provider_execution: observed identity does not match the run")
    invocation = evidence.get("invocation")
    if not isinstance(invocation, Mapping) or invocation.get("exit_code") != 0:
        errors.append(f"run[{run.get('run_id')}].provider_execution: successful provider invocation is missing")
    events = evidence.get("events")
    if not isinstance(events, list):
        errors.append(f"run[{run.get('run_id')}].provider_execution: event record is missing")
        return
    by_kind = {event.get("kind"): event for event in events if isinstance(event, Mapping)}
    for kind in ("provider_request", "provider_response", "harness_result"):
        if kind not in by_kind:
            errors.append(f"run[{run.get('run_id')}].provider_execution: {kind} event is missing")
    request = by_kind.get("provider_request", {})
    if request.get("request_sha256") != run.get("inputs", {}).get("request_sha256"):
        errors.append(f"run[{run.get('run_id')}].provider_execution: provider request is not bound to the input snapshot")
    response = by_kind.get("provider_response", {})
    if response.get("status") != "COMPLETED" or response.get("exit_code") != 0:
        errors.append(f"run[{run.get('run_id')}].provider_execution: provider response was not completed")
    result = by_kind.get("harness_result", {})
    if result.get("status") != "COMPLETED" or result.get("exit_code") != 0 or result.get("plan_sha256") != plan_hash:
        errors.append(f"run[{run.get('run_id')}].provider_execution: harness result is not bound to the observed plan")


def _verify_operation_trace(run: Mapping[str, Any], errors: list[str]) -> None:
    ref = run.get("operation_trace")
    if not isinstance(ref, Mapping):
        errors.append(f"run[{run.get('run_id')}]: operation trace is missing")
        return
    trace = _load_json_ref(ref, "path", "sha256", f"run[{run.get('run_id')}].operation_trace", errors)
    if trace is None:
        return
    if trace.get("contract_version") != "agent-operation-trace/v1" or trace.get("run_id") != run.get("run_id"):
        errors.append(f"run[{run.get('run_id')}].operation_trace: trace identity or contract does not match")
    events = trace.get("events")
    if not isinstance(events, list):
        errors.append(f"run[{run.get('run_id')}].operation_trace: events are missing")
        return
    questions = sum(1 for event in events if isinstance(event, Mapping) and event.get("kind") in QUESTION_KINDS)
    forbidden = sorted({str(event.get("operation")) for event in events if isinstance(event, Mapping) and event.get("operation") in FORBIDDEN_OPERATIONS})
    if questions != run.get("operation_trace", {}).get("human_questions"):
        errors.append(f"run[{run.get('run_id')}].operation_trace: declared human question count does not match events")
    if forbidden != sorted(run.get("operation_trace", {}).get("forbidden_operations", [])):
        errors.append(f"run[{run.get('run_id')}].operation_trace: declared forbidden operations do not match events")
    sources = {event.get("source") for event in events if isinstance(event, Mapping) and event.get("kind") == "instruction"}
    if sources != set(run.get("inputs", {}).get("instruction_sources", [])):
        errors.append(f"run[{run.get('run_id')}].operation_trace: instruction sources do not match the supplied entrypoint")
    if not any(isinstance(event, Mapping) and event.get("kind") == "entrypoint" and event.get("source") == "README.md" for event in events):
        errors.append(f"run[{run.get('run_id')}].operation_trace: README entrypoint event is missing")


def _verify_delivery(run: Mapping[str, Any], errors: list[str]) -> None:
    ref = run.get("delivery")
    if not isinstance(ref, Mapping):
        errors.append(f"run[{run.get('run_id')}]: delivery evidence is missing")
        return
    delivery = _load_json_ref(ref, "path", "sha256", f"run[{run.get('run_id')}].delivery", errors)
    if delivery is None:
        return
    expected = {
        "contract_version": "delivery-completion/v1",
        "target": "project-local",
        "status": "COMPLETED",
        "missing": [],
    }
    if delivery != expected:
        errors.append(f"run[{run.get('run_id')}].delivery: requested project-local completion is not observed")


def _verify_owners(run: Mapping[str, Any], code_pins: Mapping[str, Any], errors: list[str]) -> bool:
    seen: set[str] = set()
    valid = True
    for index, item in enumerate(run.get("owner_revalidation", [])):
        label = f"run[{run.get('run_id')}].owner_revalidation[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{label}: owner record must be an object")
            valid = False
            continue
        repository = item.get("repository")
        if not isinstance(repository, str) or repository in seen:
            errors.append(f"{label}: owner repository is missing or duplicated")
            valid = False
        seen.add(str(repository))
        if repository not in code_pins or item.get("observed_commit") != code_pins.get(repository):
            errors.append(f"{label}: observed owner commit does not match the fixed code pin")
            valid = False
        evidence = _load_json_ref(item, "evidence_path", "evidence_sha256", label, errors)
        if evidence is None:
            valid = False
            continue
        if evidence.get("status") not in {"PASS", "PASSED", "COMPLETE", "COMPLETED"} or evidence.get("repository") != repository or evidence.get("observed_commit") != item.get("observed_commit"):
            errors.append(f"{label}: owner evidence content does not revalidate the declared repository and commit")
            valid = False
    missing = sorted(REQUIRED_OWNERS - seen)
    if missing:
        errors.append(f"run[{run.get('run_id')}].owner_revalidation: missing owners {missing}")
        valid = False
    return valid


def _verify_adoption(run: Mapping[str, Any], previous: Mapping[str, Any] | None, errors: list[str]) -> bool:
    item = run.get("knowledge_adoption")
    if not isinstance(item, Mapping):
        errors.append(f"run[{run.get('run_id')}]: knowledge adoption evidence is missing")
        return False
    label = f"run[{run.get('run_id')}].knowledge_adoption"
    evidence = _load_json_ref(item, "evidence_path", "evidence_sha256", label, errors)
    content = _load_json_ref(item, "content_check_path", "content_check_sha256", f"{label}.content_check", errors)
    if evidence is None or content is None:
        return False
    status = item.get("status")
    if evidence.get("contract_version") != "knowledge-adoption-evidence/v1" or evidence.get("run_id") != run.get("run_id") or evidence.get("status") != status:
        errors.append(f"{label}: evidence content does not match the run or declared status")
        return False
    if content.get("contract_version") != "knowledge-adoption-content-check/v1" or content.get("run_id") != run.get("run_id"):
        errors.append(f"{label}: content check contract or run identity is invalid")
        return False
    if status == "BASELINE":
        if previous is not None or item.get("source_run_id") is not None or content.get("status") != "BASELINE" or content.get("adopted_count") != 0 or content.get("content_checked") is not True:
            errors.append(f"{label}: first run must record an inspected baseline without adoption")
            return False
        return True
    if previous is None or item.get("source_run_id") != previous.get("run_id") or content.get("status") != "ADOPTED":
        errors.append(f"{label}: second run must point to the first run in the same mode")
        return False
    if content.get("content_checked") is not True or not isinstance(content.get("adopted_count"), int) or content.get("adopted_count", 0) < 1 or content.get("changed_decision_or_step") is not True:
        errors.append(f"{label}: second run lacks a positive content adoption decision")
        return False
    source_path = _absolute_file(content.get("source_content_path"), f"{label}.source_content_path", errors)
    target_path = _absolute_file(content.get("target_content_path"), f"{label}.target_content_path", errors)
    source_hash = _verify_hash(source_path, content.get("source_content_sha256"), f"{label}.source_content_sha256", errors)
    target_hash = _verify_hash(target_path, content.get("target_content_sha256"), f"{label}.target_content_sha256", errors)
    if source_hash is None or target_hash is None or source_hash == target_hash:
        errors.append(f"{label}: adopted content must compare two distinct inspected snapshots")
        return False
    comparisons = content.get("comparisons")
    if not isinstance(comparisons, list) or not any(isinstance(record, Mapping) and record.get("disposition") == "ADOPTED" for record in comparisons):
        errors.append(f"{label}: content check has no ADOPTED comparison record")
        return False
    return True


def verify_manifest(manifest_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"contract_version": "autonomous-plan-acceptance/v1", "status": "FAILED", "errors": [f"manifest cannot be read: {exc}"]}
    errors.extend(_schema_errors(manifest))
    if errors:
        return {"contract_version": "autonomous-plan-acceptance/v1", "status": "FAILED", "errors": errors}
    if manifest.get("status") == "NOT_RUN":
        return {
            "contract_version": "autonomous-plan-acceptance/v1",
            "status": "NOT_RUN",
            "ac11": "NOT_RUN",
            "provider": manifest["provider"]["type"],
            "blocker": manifest.get("blocker"),
            "checks": {"manifest_schema": "PASS", "provider_matrix": "NOT_RUN", "ac11": "NOT_RUN"},
            "errors": [],
        }

    provider = manifest["provider"]
    if provider.get("available") is not True or provider.get("external_agent") is not True:
        errors.append("provider: a PASS manifest requires an available external provider")
    code_pins = manifest["code_pins"]
    knowledge_pins = manifest["knowledge_pins"]
    if set(code_pins) != REQUIRED_OWNERS or set(knowledge_pins) != REQUIRED_OWNERS:
        errors.append("manifest: code_pins and knowledge_pins must cover all eight declared owners")
    runs = manifest["runs"]
    expected = {(mode, sequence) for mode in MODES for sequence in (1, 2)}
    observed = {(run.get("mode"), run.get("sequence")) for run in runs if isinstance(run, Mapping)}
    if observed != expected or len(runs) != 6:
        errors.append("runs: exactly two runs for each resume, new-clone, and fork mode are required")
    seen_ids: set[str] = set()
    by_mode: dict[tuple[str, int], Mapping[str, Any]] = {}
    run_checks: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        run_id = str(run.get("run_id"))
        if run_id in seen_ids:
            errors.append(f"run[{run_id}]: duplicate run ID")
        seen_ids.add(run_id)
        by_mode[(str(run.get("mode")), int(run.get("sequence", 0)))] = run
        if run.get("code_pins") != code_pins or run.get("knowledge_pins") != knowledge_pins:
            errors.append(f"run[{run_id}]: code or knowledge pins drift from the manifest fixed refs")
        artifacts = _artifact_hashes(run, errors)
        plan_hash = artifacts.get("plan")
        _verify_provider_execution(manifest, run, plan_hash, errors)
        _verify_operation_trace(run, errors)
        _verify_delivery(run, errors)
        owner_ok = _verify_owners(run, code_pins, errors)
        run_checks.append({"run_id": run_id, "owner_revalidation": owner_ok, "plan_hash": plan_hash})
    adoption_ok = True
    for mode in MODES:
        first = by_mode.get((mode, 1))
        second = by_mode.get((mode, 2))
        if first is not None:
            adoption_ok = _verify_adoption(first, None, errors) and adoption_ok
        if second is not None:
            adoption_ok = _verify_adoption(second, first, errors) and adoption_ok
    if any(run.get("human_gate") != "NOT_REQUIRED" for run in runs if isinstance(run, Mapping)):
        errors.append("runs: every delivery must record human_gate=NOT_REQUIRED")
    computed = {
        "six_runs": len(runs) == 6 and observed == expected and len(seen_ids) == 6,
        "owner_revalidation": all(item["owner_revalidation"] for item in run_checks) and len(run_checks) == 6,
        "delivery_completion": not any("project-local completion" in error for error in errors),
        "zero_human_questions": not any("human question count" in error for error in errors),
        "second_run_adoption": adoption_ok,
        "fork_upstream_unchanged": not any(isinstance(run, Mapping) and any(
            isinstance(event, Mapping) and event.get("operation") in {"upstream_write", "remote_push"}
            for event in _trace_events(run)
        ) for run in runs),
    }
    for key, value in computed.items():
        if manifest["acceptance"].get(key) is not value:
            errors.append(f"acceptance.{key}: self-declared value does not match inspected evidence")
    if not all(computed.values()) or manifest["acceptance"].get("ac11") != "PASS":
        errors.append("acceptance: AP-06 cannot be PASS while an inspected acceptance is incomplete")
    return {
        "contract_version": "autonomous-plan-acceptance/v1",
        "status": "PASS" if not errors else "FAILED",
        "ac11": "PASS" if not errors else "NOT_RUN",
        "provider": provider["type"],
        "run_count": len(runs),
        "checks": computed,
        "run_checks": run_checks,
        "errors": errors,
    }


def _trace_events(run: Mapping[str, Any]) -> list[Any]:
    ref = run.get("operation_trace")
    if not isinstance(ref, Mapping):
        return []
    path = Path(str(ref.get("path", "")))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    return value.get("events", []) if isinstance(value, Mapping) and isinstance(value.get("events"), list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="absolute external AP-06 evidence manifest")
    args = parser.parse_args(argv)
    manifest = args.manifest.expanduser()
    if not manifest.is_absolute():
        print(json.dumps({"status": "FAILED", "errors": ["--manifest must be an absolute path"]}, ensure_ascii=False))
        return 1
    report = verify_manifest(manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("status") == "PASS" or report.get("status") == "NOT_RUN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
