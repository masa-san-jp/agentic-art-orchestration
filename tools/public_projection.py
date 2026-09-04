#!/usr/bin/env python3
"""Validate the closed, metadata-only public projection contracts.

This contract-stage tool does not read or mutate a public target.  The later
prepare, plan, and apply tasks own filesystem projection; keeping this module
validation-only makes an accidental public write impossible at this stage.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.security import PUBLIC_PROJECTION_FINDING_CODES, scan_public_projection  # noqa: E402
from tools.validate import _schema_errors, load_json  # noqa: E402


LAYOUT_SCHEMA_PATH = ROOT / "schemas/public-project-layout.schema.json"
REQUEST_SCHEMA_PATH = ROOT / "schemas/public-projection-request.schema.json"
APPROVAL_SCHEMA_PATH = ROOT / "schemas/public-projection-approval.schema.json"
RESULT_SCHEMA_PATH = ROOT / "schemas/public-projection-result.schema.json"
HASH64 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RELATIVE_PATH = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
PLAN_TARGETS = {"README.md", "plan.md"}
WORK_TARGETS = {"README.md", "record.md"}


class PublicProjectionError(ValueError):
    """A public projection contract cannot be accepted safely."""


def _error(detail: str, remediation: str) -> str:
    return f"public projection: {detail}; remediation: {remediation}"


def _schema_errors_for(value: object, schema_path: Path, source: str) -> list[str]:
    try:
        schema = load_json(schema_path)
    except ValueError as exc:
        return [_error(f"schema unavailable for {source}: {exc}", "restore the checked-in public projection schema")]
    return _schema_errors(value, schema, source)


def canonical_json_bytes(value: object) -> bytes:
    """Canonical UTF-8 JSON used for request/result hashes."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_file_descriptors(files: list[Mapping[str, object]]) -> list[dict[str, str]]:
    """Return only hash-bearing file identity fields in stable order."""
    descriptors = [
        {
            "role": str(file["role"]),
            "source_locator": str(file["source_locator"]),
            "target_locator": str(file["target_locator"]),
            "sha256": str(file["sha256"]),
        }
        for file in files
    ]
    return sorted(descriptors, key=lambda item: (item["role"], item["source_locator"], item["target_locator"]))


def record_file_sha256(files: list[Mapping[str, object]]) -> str:
    """Calculate the immutable record source hash required by the request."""
    return sha256_hex(canonical_file_descriptors(files))


def request_sha256(request: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(request)).hexdigest()


def approval_sha256(approval: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(approval)).hexdigest()


def validate_layout(value: object, source: str = "public-project-layout") -> list[str]:
    return _schema_errors_for(value, LAYOUT_SCHEMA_PATH, source)


def _record_error(index: int, detail: str, remediation: str) -> str:
    return _error(f"records[{index}] {detail}", remediation)


def validate_request(value: object, source: str = "public-projection-request") -> list[str]:
    """Validate shape and deterministic record/file relationships.

    Clearance is deliberately not required here: a draft request may carry
    ``unknown`` values.  ``request_policy_findings`` is the separate gate that
    prevents such a draft from being treated as publishable.
    """
    errors = _schema_errors_for(value, REQUEST_SCHEMA_PATH, source)
    if not isinstance(value, Mapping):
        return errors
    records = value.get("records")
    if not isinstance(records, list):
        return errors
    source_keys: set[tuple[str, str]] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        kind = record.get("record_kind")
        files = record.get("files")
        source_data = record.get("source")
        if not isinstance(files, list) or not isinstance(source_data, Mapping):
            continue
        body_files = [file for file in files if isinstance(file, Mapping) and file.get("role") == "body"]
        if len(body_files) != 1:
            errors.append(_record_error(index, "must contain exactly one body file", "add one plan.md or record.md body and no duplicate body"))
        expected_body = "plan.md" if kind == "plan" else "record.md"
        if body_files and body_files[0].get("target_locator") != expected_body:
            errors.append(_record_error(index, f"body target must be {expected_body!r}", "use the kind-specific body target"))
        seen_targets: set[str] = set()
        for file_index, file in enumerate(files):
            if not isinstance(file, Mapping):
                continue
            target = file.get("target_locator")
            if isinstance(target, str) and target in seen_targets:
                errors.append(_record_error(index, f"files[{file_index}] duplicates target {target!r}", "give every projected file a unique target locator"))
            if isinstance(target, str):
                seen_targets.add(target)
            role = file.get("role")
            if role == "readme" and target != "README.md":
                errors.append(_record_error(index, "readme must target README.md", "use README.md or omit the optional readme"))
            if role == "media" and isinstance(target, str) and not target.startswith("media/"):
                errors.append(_record_error(index, "media must target media/", "put media under the collection media directory"))
            if role == "process" and (kind != "work" or not isinstance(target, str) or not target.startswith("process/")):
                errors.append(_record_error(index, "process files are work-only and must target process/", "use process/<name> for work process files"))
            if isinstance(file.get("source_locator"), str) and ".." in file["source_locator"].split("/"):
                errors.append(_record_error(index, "source locator contains traversal", "use a normalized relative source locator"))
        if isinstance(source_data.get("sha256"), str) and all(isinstance(file, Mapping) for file in files):
            calculated = record_file_sha256(files)
            if source_data["sha256"] != calculated:
                errors.append(_record_error(index, "source.sha256 does not match canonical file descriptors", "recalculate the record hash from role/source_locator/target_locator/file sha256"))
        source_key = (str(kind), str(source_data.get("sha256")))
        if source_key in source_keys:
            errors.append(_record_error(index, "duplicates a record source key", "include each kind and source hash once per request"))
        source_keys.add(source_key)
    return errors


def request_policy_findings(value: Mapping[str, object]) -> list[dict[str, str]]:
    """Return sanitized policy/security findings without changing the request."""
    findings: list[dict[str, str]] = []
    records = value.get("records")
    if isinstance(records, list):
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                continue
            publication = record.get("publication")
            if not isinstance(publication, Mapping):
                continue
            for field in ("visibility", "rights_status", "consent_status"):
                if publication.get(field) != ("public" if field == "visibility" else "cleared"):
                    findings.append({
                        "code": "UNKNOWN_CLEARANCE",
                        "location": f"records[{index}].publication.{field}",
                        "remediation": "obtain explicit human clearance evidence and set the declared status before projection",
                    })
            files = record.get("files")
            if isinstance(files, list):
                for file_index, file in enumerate(files):
                    if isinstance(file, Mapping) and file.get("role") in {"media", "process"} and file.get("rights_status") != "cleared":
                        findings.append({
                            "code": "UNAPPROVED_MEDIA",
                            "location": f"records[{index}].files[{file_index}].rights_status",
                            "remediation": "obtain explicit rights clearance for media/process files before projection",
                        })
    findings.extend(scan_public_projection(value, "public-projection-request"))
    unique = {json.dumps(item, ensure_ascii=False, sort_keys=True): item for item in findings}
    return [unique[key] for key in sorted(unique)]


def projection_policy_status(value: Mapping[str, object]) -> str:
    """Return a non-mutating policy decision for a request draft."""
    structural = validate_request(value)
    if structural or request_policy_findings(value):
        return "BLOCKED_POLICY"
    return "READY_FOR_DRY_RUN"


def _parse_timestamp(value: object, label: str) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def validate_approval(value: object, source: str = "public-projection-approval") -> list[str]:
    errors = _schema_errors_for(value, APPROVAL_SCHEMA_PATH, source)
    if not isinstance(value, Mapping):
        return errors
    approved_at = _parse_timestamp(value.get("approved_at"), "approved_at")
    expires_at = _parse_timestamp(value.get("expires_at"), "expires_at")
    if approved_at is not None and expires_at is not None and expires_at <= approved_at:
        errors.append(_error("expires_at must be later than approved_at", "set a positive approval validity window"))
    return errors


def validate_result(value: object, source: str = "public-projection-result") -> list[str]:
    errors = _schema_errors_for(value, RESULT_SCHEMA_PATH, source)
    if not isinstance(value, Mapping):
        return errors
    status = value.get("status")
    target = value.get("target")
    human_gate = value.get("human_gate")
    changed_paths = value.get("changed_paths")
    if not isinstance(target, Mapping) or not isinstance(human_gate, Mapping) or not isinstance(changed_paths, list):
        return errors
    mutation_count = target.get("mutation_count")
    if status != "APPLIED":
        if mutation_count != 0 or changed_paths:
            errors.append(_error(f"{status} result reports target mutation", "record zero changed paths and mutation_count for a blocked or dry-run result"))
    if status == "DRY_RUN_READY":
        if value.get("approval_sha256") is not None or human_gate.get("status") != "BLOCKED_HUMAN":
            errors.append(_error("DRY_RUN_READY has an approval or wrong human gate", "keep approval absent and report BLOCKED_HUMAN until human approval"))
    if status == "APPLIED":
        if not isinstance(value.get("approval_sha256"), str) or human_gate.get("status") != "APPROVED":
            errors.append(_error("APPLIED result lacks a matching human approval envelope", "require public_share approval before local projection"))
    return errors


def validate_contracts(
    *,
    layout: object | None = None,
    request: object | None = None,
    approval: object | None = None,
    result: object | None = None,
) -> list[str]:
    errors: list[str] = []
    if layout is not None:
        errors.extend(validate_layout(layout))
    if request is not None:
        errors.extend(validate_request(request))
    if approval is not None:
        errors.extend(validate_approval(approval))
    if result is not None:
        errors.extend(validate_result(result))
    return errors


def _load_document(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PublicProjectionError(_error(f"cannot read {path.name}: {exc}", "supply a UTF-8 JSON or YAML contract file")) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate public projection contracts without touching a public target")
    parser.add_argument("command", choices=["validate"])
    parser.add_argument("--layout", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args(argv)
    if not any((args.layout, args.request, args.approval, args.result)):
        parser.error("validate requires at least one contract input")
    try:
        values = {
            "layout": _load_document(args.layout) if args.layout else None,
            "request": _load_document(args.request) if args.request else None,
            "approval": _load_document(args.approval) if args.approval else None,
            "result": _load_document(args.result) if args.result else None,
        }
        errors = validate_contracts(**values)
    except (OSError, PublicProjectionError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "errors": [str(exc)]}, ensure_ascii=False, sort_keys=True))
        return 2
    output: dict[str, Any] = {"status": "PASSED" if not errors else "FAILED", "errors": errors}
    if values["request"] is not None and isinstance(values["request"], Mapping):
        output["policy_status"] = projection_policy_status(values["request"])
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
