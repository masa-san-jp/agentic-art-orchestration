#!/usr/bin/env python3
"""Assess aggregate viewer response records without treating estimates as acceptance."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable

try:
    from tools.validate import _schema_errors, load_json
except ModuleNotFoundError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.validate import _schema_errors, load_json


Z95 = 1.959963984540054
SHA40 = re.compile(r"^[0-9a-f]{40}$")
RECORD_ID = re.compile(r"^VRR-[A-Z0-9][A-Z0-9._-]*$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#?&=%+-]*$")
SAFE_TAG = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SAFE_MODE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SHA256_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE = re.compile(r"(?<![A-Za-z0-9])\+?[0-9][0-9 ()-]{7,}[0-9](?![A-Za-z0-9])")
ASSESSMENT_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/viewer-response-assessment.schema.json"
RECORD_FIELDS = {
    "record_id", "work_id", "requirement_id", "source_kind", "presentation_mode",
    "requirement_tags", "sample_size", "outcome_counts", "evidence_refs", "certainty",
    "consent_scope", "source_commit", "observed_at", "dedup_key",
}


class ViewerResponseGateError(ValueError):
    """Raised when an assessment input or review gate is unsafe."""


def wilson95(successes: int, trials: int) -> dict[str, float] | None:
    if trials <= 0:
        return None
    z2 = Z95 * Z95
    proportion = successes / trials
    denominator = 1 + z2 / trials
    centre = (proportion + z2 / (2 * trials)) / denominator
    margin = Z95 * math.sqrt((proportion * (1 - proportion) / trials) + (z2 / (4 * trials * trials))) / denominator
    return {"level": 0.95, "lower": round(max(0.0, centre - margin), 6), "upper": round(min(1.0, centre + margin), 6)}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ViewerResponseGateError(f"records file not found: {path}")
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ViewerResponseGateError(f"{path}:{number}: invalid JSONL: {exc}") from exc
        if not isinstance(value, dict):
            raise ViewerResponseGateError(f"{path}:{number}: record must be an object")
        records.append(value)
    return records


def _reject_sensitive(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {"name", "email", "phone", "contact", "free_text", "raw_text", "diagnosis", "disease", "psychological_profile"}:
                raise ViewerResponseGateError(f"{path}.{key}: personal, free-text, or psychological fields are forbidden")
            _reject_sensitive(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive(child, f"{path}[{index}]")
    elif isinstance(value, str):
        if (
            any(marker in value.upper() for marker in ("PRIVATE_RAW", "RESTRICTED"))
            or "\n" in value
            or "\r" in value
            or EMAIL.search(value)
            or PHONE.search(value)
            or value.startswith(("/", "~/", "file://"))
        ):
            raise ViewerResponseGateError(f"{path}: prohibited raw/classified content")


def _dedup_key(record: dict[str, Any]) -> str:
    payload = [record["work_id"], record["requirement_id"], record["presentation_mode"], sorted(record["evidence_refs"])]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_record(record: dict[str, Any], index: int) -> None:
    _reject_sensitive(record, f"records[{index}]")
    if set(record) != RECORD_FIELDS:
        missing = sorted(RECORD_FIELDS - set(record))
        unknown = sorted(set(record) - RECORD_FIELDS)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unknown:
            detail.append("unknown=" + ",".join(unknown))
        raise ViewerResponseGateError(f"records[{index}]: not a complete viewer-response-record/v1 record ({'; '.join(detail)})")
    if not RECORD_ID.fullmatch(record["record_id"]) or not all(isinstance(record.get(key), str) and SAFE_ID.fullmatch(record[key]) for key in ("work_id", "requirement_id")):
        raise ViewerResponseGateError(f"records[{index}]: identifiers are not safe opaque IDs")
    if record.get("source_kind") not in {"measured", "external"} or not isinstance(record.get("presentation_mode"), str) or not SAFE_MODE.fullmatch(record["presentation_mode"]):
        raise ViewerResponseGateError(f"records[{index}]: source kind or presentation mode is invalid")
    tags = record.get("requirement_tags")
    if not isinstance(tags, list) or not tags or len(set(tags)) != len(tags) or tags != sorted(tags) or any(not isinstance(tag, str) or not SAFE_TAG.fullmatch(tag) for tag in tags):
        raise ViewerResponseGateError(f"records[{index}]: requirement_tags must be sorted, unique, and safe")
    sample = record.get("sample_size")
    counts = record.get("outcome_counts")
    if not isinstance(sample, int) or isinstance(sample, bool) or sample < 0 or not isinstance(counts, dict) or set(counts) != {"pass", "fail", "unknown"} or any(not isinstance(counts[key], int) or isinstance(counts[key], bool) or counts[key] < 0 for key in counts) or sum(counts.values()) != sample:
        raise ViewerResponseGateError(f"records[{index}]: aggregate counts do not sum to sample_size")
    refs = record.get("evidence_refs")
    if not isinstance(refs, list) or not refs or len(set(refs)) != len(refs) or refs != sorted(refs) or any(not isinstance(ref, str) or not SAFE_REF.fullmatch(ref) or not ref.startswith(("https://", "doi:", "production-result:", "viewer-response:")) for ref in refs):
        raise ViewerResponseGateError(f"records[{index}]: evidence_refs must be sorted opaque references")
    if record["certainty"] not in {"high", "medium", "low", "unknown"}:
        raise ViewerResponseGateError(f"records[{index}]: certainty is invalid")
    if record.get("source_kind") == "external" and (sample != 0 or any(counts.values())):
        raise ViewerResponseGateError(f"records[{index}]: external evidence cannot contain measured counts")
    if record.get("consent_scope") != "aggregate-only" or not SHA40.fullmatch(str(record.get("source_commit"))):
        raise ViewerResponseGateError(f"records[{index}]: consent scope or source commit is invalid")
    if not isinstance(record["observed_at"], str):
        raise ViewerResponseGateError(f"records[{index}]: observed_at must be RFC3339")
    try:
        observed_at = datetime.fromisoformat(record["observed_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ViewerResponseGateError(f"records[{index}]: observed_at must be RFC3339") from exc
    if observed_at.tzinfo is None:
        raise ViewerResponseGateError(f"records[{index}]: observed_at must include a timezone")
    if not isinstance(record["dedup_key"], str) or not SHA256_REF.fullmatch(record["dedup_key"]) or record["dedup_key"] != _dedup_key(record):
        raise ViewerResponseGateError(f"records[{index}]: dedup_key does not match canonical record inputs")


def assess_records(
    records: Iterable[dict[str, Any]],
    *,
    work_id: str,
    requirement_id: str,
    presentation_mode: str,
    requirement_tags: Iterable[str],
) -> dict[str, Any]:
    records = list(records)
    for index, record in enumerate(records):
        _validate_record(record, index)
    requested_tags = set(requirement_tags)
    if not requested_tags or any(not isinstance(tag, str) or not SAFE_TAG.fullmatch(tag) for tag in requested_tags) or not SAFE_ID.fullmatch(work_id) or not SAFE_ID.fullmatch(requirement_id) or not SAFE_MODE.fullmatch(presentation_mode):
        raise ViewerResponseGateError("assessment selectors must be non-empty safe identifiers")
    matching = sorted((record for record in records if record["work_id"] == work_id and record["requirement_id"] == requirement_id and record["presentation_mode"] == presentation_mode and requested_tags.intersection(record["requirement_tags"])), key=lambda record: record["record_id"])
    measured = [record for record in matching if record["source_kind"] == "measured"]
    external = [record for record in matching if record["source_kind"] == "external"]
    counts = {key: sum(record["outcome_counts"][key] for record in measured) for key in ("pass", "fail", "unknown")}
    sample = sum(record["sample_size"] for record in measured)
    interval = wilson95(counts["pass"], counts["pass"] + counts["fail"])
    external_refs = sorted({ref for record in external for ref in record["evidence_refs"]})
    if sample == 0 and len(external_refs) >= 2:
        status = "EXTERNALLY_SUPPORTED"
    elif sample < 5:
        status = "UNKNOWN"
    elif interval and interval["lower"] >= 0.60:
        status = "SUPPORTED"
    elif interval and interval["upper"] < 0.60:
        status = "CONTRADICTED"
    else:
        status = "UNKNOWN"
    review_required = status in {"UNKNOWN", "CONTRADICTED", "EXTERNALLY_SUPPORTED"}
    assessment = {
        "schema_id": "viewer-response-assessment/v1",
        "assessment_id": f"VRA-{work_id.replace('/', '-')}-{requirement_id.replace('/', '-')}-{presentation_mode}".upper(),
        "work_id": work_id,
        "requirement_id": requirement_id,
        "presentation_mode": presentation_mode,
        "matching_tags": sorted({tag for record in matching for tag in requested_tags.intersection(record["requirement_tags"])} or requested_tags),
        "status": status,
        "measured_sample_size": sample,
        "outcome_counts": counts,
        "confidence_interval": interval,
        "source_record_ids": [record["record_id"] for record in matching],
        "external_evidence_refs": external_refs,
        "conflict": bool(measured and external),
        "review_required": review_required,
        "review_kind": "BLIND_OR_FRAME" if review_required else "NONE",
        "source_commits": sorted({record["source_commit"] for record in matching}),
    }
    errors = _schema_errors(assessment, load_json(ASSESSMENT_SCHEMA))
    if errors:
        raise ViewerResponseGateError("assessment schema failure: " + "; ".join(errors))
    return assessment


def validate_plan_review_requirement(assessment: dict[str, Any], plan: dict[str, Any]) -> None:
    """Require a blind/frame test for an affected viewer-facing requirement."""
    if assessment["status"] not in {"UNKNOWN", "CONTRADICTED", "EXTERNALLY_SUPPORTED"}:
        return
    requirements = plan.get("requirements", plan.get("mandatory_requirements", []))
    if not isinstance(requirements, list):
        raise ViewerResponseGateError("production plan has no requirements collection for viewer review matching")
    target = next((item for item in requirements if isinstance(item, dict) and item.get("id") == assessment["requirement_id"]), None)
    if not isinstance(target, dict) or target.get("viewer_facing") is not True:
        return
    test_ids = target.get("acceptance_test_ids", [])
    tests = plan.get("acceptance_tests", [])
    if not isinstance(test_ids, list) or not isinstance(tests, list):
        raise ViewerResponseGateError("viewer-facing requirement is missing acceptance test references")
    selected = [test for test in tests if isinstance(test, dict) and test.get("id") in test_ids]
    review_text = " ".join(str(test.get(key, "")) for test in selected for key in ("title", "method", "description", "pass_condition")).lower()
    if not re.search(r"\bblind\b|\bframe\b", review_text):
        raise ViewerResponseGateError("PLANNING_VIEWER_REVIEW_REQUIRED: UNKNOWN/CONTRADICTED estimate requires a blind or frame review acceptance test")


def assess_and_gate(records: Iterable[dict[str, Any]], *, work_id: str, requirement_id: str, presentation_mode: str, requirement_tags: Iterable[str], plan: dict[str, Any] | None = None) -> dict[str, Any]:
    assessment = assess_records(records, work_id=work_id, requirement_id=requirement_id, presentation_mode=presentation_mode, requirement_tags=requirement_tags)
    if plan is not None:
        validate_plan_review_requirement(assessment, plan)
    return assessment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--requirement-id", required=True)
    parser.add_argument("--presentation-mode", required=True)
    parser.add_argument("--requirement-tag", action="append", required=True)
    parser.add_argument("--production-plan", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        records = _read_jsonl(args.records)
        plan = load_json(args.production_plan) if args.production_plan else None
        result = assess_and_gate(records, work_id=args.work_id, requirement_id=args.requirement_id, presentation_mode=args.presentation_mode, requirement_tags=args.requirement_tag, plan=plan)
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
