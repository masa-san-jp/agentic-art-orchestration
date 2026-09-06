#!/usr/bin/env python3
"""Validate, prepare, and apply closed public projection contracts.

The normal request-backed projection remains human-approval-gated.  A separate
in-process ``AUTOMATIC_PLAN`` path is available only to the canonical run and
batch producers for completed production plans; it never performs Git or
remote publication operations.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.security import PUBLIC_PROJECTION_FINDING_CODES, scan_public_projection  # noqa: E402
from tools.output_destinations import (  # noqa: E402
    manifest_child_roots,
    resolve_destinations,
    resolve_run_destination,
    validate_destination_resolution,
)
from tools.validate import _schema_errors, load_json  # noqa: E402


LAYOUT_SCHEMA_PATH = ROOT / "schemas/public-project-layout.schema.json"
REQUEST_SCHEMA_PATH = ROOT / "schemas/public-projection-request.schema.json"
APPROVAL_SCHEMA_PATH = ROOT / "schemas/public-projection-approval.schema.json"
RESULT_SCHEMA_PATH = ROOT / "schemas/public-projection-result.schema.json"
HASH64 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RELATIVE_PATH = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
SOURCE_RELATIVE_PATH = re.compile(r"^[A-Za-z0-9._:-]+(?:/[A-Za-z0-9._:-]+)*$")
PLAN_TARGETS = {"README.md", "plan.md"}
WORK_TARGETS = {"README.md", "record.md"}
PREPARE_ROOT = "public-projection-candidates"
PRODUCTION_REPOSITORY = "agentic-art-production"
PREPARE_STATUSES = {"PASSED", "ALREADY_PREPARED", "REFRESHED", "NOT_AVAILABLE"}
AUTOMATIC_PLAN_MODE = "AUTOMATIC_PLAN"
HUMAN_APPROVED_MODE = "HUMAN_APPROVED"
AUTOMATIC_AUTHORITY_VERSION = "automatic-plan-projection-authority/v1"
AUTOMATIC_PLAN_STATUSES = {
    "APPLIED",
    "ALREADY_PROJECTED",
    "BLOCKED_CONFIGURATION",
    "BLOCKED_POLICY",
    "BLOCKED_CONFLICT",
    "FAILED",
}
PROJECT_STATUSES = {
    "DRY_RUN_READY",
    "BLOCKED_HUMAN",
    "APPLIED",
    "ALREADY_PROJECTED",
    "BLOCKED_CONFIGURATION",
    "BLOCKED_POLICY",
    "BLOCKED_CONFLICT",
    "FAILED",
}
INIT_STATUSES = {"DRY_RUN_READY", "APPLIED", "BLOCKED_CONFLICT", "FAILED"}
DEFAULT_LAYOUT = {
    "contract_version": "public-project-layout/v1",
    "canonical_plan": {"source_repository": "agentic-art-production", "source_artifact": "03_plan/production-plan.md", "target_artifact": "plan.md", "projection_contract": "canonical-plan-projection/v2", "body_transform": "none", "receiver_validator": "python3 tools/validate.py --check", "migration_registry": "plans/migration.yaml"},
    "collections": {"plans": "plans", "works": "works"},
    "catalog_markers": {
        "start": "<!-- agentic-art:catalog:start -->",
        "end": "<!-- agentic-art:catalog:end -->",
    },
    "media_policy": {
        "max_file_bytes": 50000000,
        "allowed_extensions": [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".mp4", ".webm", ".mp3", ".wav", ".pdf", ".txt", ".md", ".py"],
    },
}
INDEX_VERSION = 1
INDEX_FILES = ("plans/index.yaml", "works/index.yaml")
MIME_BY_EXTENSION = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".py": "text/x-python",
    ".svg": "image/svg+xml",
    ".txt": "text/plain",
    ".wav": "audio/wav",
    ".webm": "video/webm",
    ".webp": "image/webp",
}


class PublicProjectionError(ValueError):
    """A public projection contract cannot be accepted safely."""


class PreparationError(PublicProjectionError):
    """A candidate request cannot be produced without weakening a boundary."""

    def __init__(self, code: str, location: str, remediation: str):
        self.code = code
        self.location = location
        self.remediation = remediation
        super().__init__(f"{code} at {location}; remediation: {remediation}")


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


def build_automatic_plan_authority(
    *,
    producer: str,
    source_status: str,
    source_id: str,
    source_sha256: str,
    destination_resolution: Mapping[str, object],
) -> dict[str, str]:
    """Build the closed authority envelope owned by a canonical producer."""
    if not isinstance(source_id, str) or STABLE_ID.fullmatch(source_id) is None:
        raise ValueError("automatic plan authority requires a stable source ID")
    if not isinstance(source_sha256, str) or HASH64.fullmatch(source_sha256) is None:
        raise ValueError("automatic plan authority requires a source SHA-256")
    if source_status not in {"PLAN_READY", "PASSED"}:
        raise ValueError("automatic plan authority requires PLAN_READY or PASSED")
    if producer not in {"tools/run.py", "tools/batch_run.py"}:
        raise ValueError("automatic plan authority producer is not allowlisted")
    return {
        "contract_version": AUTOMATIC_AUTHORITY_VERSION,
        "producer": producer,
        "source_status": source_status,
        "source_id": source_id,
        "source_sha256": source_sha256,
        "destination_resolution_sha256": sha256_hex(destination_resolution),
    }


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
        # The source key identifies the immutable canonical artifact.  The
        # record-level source.sha256 may change when a public-ready candidate
        # is refreshed and therefore is used only as the content hash.
        source_key = (str(kind), str(source_data.get("canonical_sha256")))
        if source_key in source_keys:
            errors.append(_record_error(index, "duplicates a record source key", "include each kind and canonical source hash once per request"))
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


def _approval_findings(
    approval: object,
    request: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, str]], str | None]:
    """Verify the human approval envelope without manufacturing any fields."""
    if not isinstance(approval, Mapping):
        return [
            _projection_finding(
                "MISSING_APPROVAL",
                "approval",
                "provide a separate public-projection-approval/v1 file signed by a human",
            )
        ], None
    structural = validate_approval(approval, "approval")
    if structural:
        expires = _parse_timestamp(approval.get("expires_at"), "expires_at")
        approved = _parse_timestamp(approval.get("approved_at"), "approved_at")
        if expires is None or approved is None:
            code = "APPROVAL_EXPIRED"
            location = "approval.approved_at" if approved is None else "approval.expires_at"
            remediation = "provide an approval with valid RFC3339 approved_at and expires_at values"
        else:
            code = "MISSING_APPROVAL"
            location = "approval"
            remediation = "repair the approval contract without changing its human authority or scope"
        return [_projection_finding(code, location, remediation)], None

    digest = approval_sha256(approval)
    if approval.get("request_sha256") != request_sha256(request):
        return [
            _projection_finding(
                "APPROVAL_MISMATCH",
                "approval.request_sha256",
                "create a new human approval for the exact canonical request hash",
            )
        ], None
    approved_at = _parse_timestamp(approval.get("approved_at"), "approved_at")
    expires_at = _parse_timestamp(approval.get("expires_at"), "expires_at")
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        observed = observed.replace(tzinfo=timezone.utc)
    if approved_at is None or expires_at is None or observed < approved_at or observed > expires_at:
        return [
            _projection_finding(
                "APPROVAL_EXPIRED",
                "approval.expires_at",
                "obtain a currently valid human approval for this request",
            )
        ], None
    return [], digest


def validate_result(value: object, source: str = "public-projection-result") -> list[str]:
    errors = _schema_errors_for(value, RESULT_SCHEMA_PATH, source)
    if not isinstance(value, Mapping):
        return errors
    status = value.get("status")
    target = value.get("target")
    human_gate = value.get("human_gate")
    changed_paths = value.get("changed_paths")
    projection_mode = value.get("projection_mode")
    if not isinstance(target, Mapping) or not isinstance(human_gate, Mapping) or not isinstance(changed_paths, list):
        return errors
    mutation_count = target.get("mutation_count")
    if status in {"DRY_RUN_READY", "BLOCKED_CONFIGURATION", "BLOCKED_HUMAN", "BLOCKED_POLICY", "BLOCKED_CONFLICT", "ALREADY_PROJECTED"}:
        if mutation_count != 0 or changed_paths:
            errors.append(_error(f"{status} result reports target mutation", "record zero changed paths and mutation_count for a non-applied result"))
    if status == "DRY_RUN_READY":
        if value.get("approval_sha256") is not None or human_gate.get("status") != "BLOCKED_HUMAN":
            errors.append(_error("DRY_RUN_READY has an approval or wrong human gate", "keep approval absent and report BLOCKED_HUMAN until human approval"))
    if projection_mode == AUTOMATIC_PLAN_MODE:
        if value.get("approval_sha256") is not None or human_gate.get("status") != "NOT_REQUIRED":
            errors.append(_error("AUTOMATIC_PLAN result has approval or a human gate", "bind automatic results to the canonical PLAN_READY/PASSED plan producer and keep approval absent"))
        if status not in AUTOMATIC_PLAN_STATUSES:
            errors.append(_error("AUTOMATIC_PLAN has an invalid status", "use a terminal automatic plan projection status"))
    elif status == "APPLIED":
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


class _QuotedStringDumper(yaml.SafeDumper):
    """Keep RFC3339 values as strings when a request is read back by YAML."""


def _quoted_string(dumper: yaml.Dumper, value: str) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style='"')


_QuotedStringDumper.add_representer(str, _quoted_string)


def _prepare_error(code: str, location: str, remediation: str) -> PreparationError:
    return PreparationError(code, location, remediation)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _valid_commit(value: object) -> bool:
    return isinstance(value, str) and SHA40.fullmatch(value) is not None and value != "0" * 40


def _valid_repo_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) is not None


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _path_token(value: str) -> str:
    """Map a stable ID to one schema-safe, collision-resistant path segment."""
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "projection"
    if token != value:
        token = f"{token}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"
    return token


def _source_locator(root: Path, raw: object, location: str) -> tuple[str, Path]:
    """Validate an absolute report path and return its safe internal locator."""
    if not isinstance(raw, (str, Path)):
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "the source report must declare an absolute internal file path")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "use an absolute path that resolves below internal_output_root without traversal")
    internal_root = root.expanduser().resolve(strict=False)
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(internal_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "the source must resolve below internal_output_root") from exc
    locator = relative.as_posix()
    if not relative.parts or SOURCE_RELATIVE_PATH.fullmatch(locator) is None:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "use a normalized internal relative locator")
    probe = internal_root
    for part in relative.parts:
        probe = probe / part
        try:
            if stat.S_ISLNK(probe.lstat().st_mode):
                raise _prepare_error("SOURCE_PATH_UNSAFE", location, "symlink source files and symlink path components are not accepted")
        except OSError as exc:
            raise _prepare_error("SOURCE_PATH_UNSAFE", location, "the source path cannot be inspected safely") from exc
    return locator, resolved


def _internal_locator(root: Path, locator: object, location: str, *, allow_dot: bool = False) -> tuple[str, Path]:
    """Resolve a request locator without following symlinks or traversal."""
    if not isinstance(locator, str) or not locator or Path(locator).is_absolute() or ".." in Path(locator).parts:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "use a normalized relative locator below internal_output_root")
    if allow_dot and locator == ".":
        relative = Path(locator)
    elif SOURCE_RELATIVE_PATH.fullmatch(locator) is None:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "use a normalized relative locator below internal_output_root")
    else:
        relative = Path(locator)
    internal_root = root.expanduser().resolve(strict=False)
    candidate = internal_root / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(internal_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "the locator must resolve below internal_output_root") from exc
    probe = internal_root
    for part in relative.parts:
        if part == ".":
            continue
        probe = probe / part
        try:
            if stat.S_ISLNK(probe.lstat().st_mode):
                raise _prepare_error("SOURCE_PATH_UNSAFE", location, "symlink source files and symlink path components are not accepted")
        except OSError as exc:
            raise _prepare_error("SOURCE_PATH_UNSAFE", location, "the locator cannot be inspected safely") from exc
    return "." if locator == "." else relative.as_posix(), resolved


def _candidate_locator(root: Path, locator: object, location: str) -> tuple[str, Path]:
    """Validate a candidate locator even when its final file is not created yet."""
    if not isinstance(locator, str) or not locator or Path(locator).is_absolute() or ".." in Path(locator).parts:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "use a normalized relative locator below internal_output_root")
    if SOURCE_RELATIVE_PATH.fullmatch(locator) is None:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "use a normalized relative locator below internal_output_root")
    relative = Path(locator)
    internal_root = root.expanduser().resolve(strict=False)
    candidate = internal_root / relative
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(internal_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "the locator must remain below internal_output_root") from exc
    probe = internal_root
    for part in relative.parts:
        probe = probe / part
        if not probe.exists():
            continue
        try:
            if stat.S_ISLNK(probe.lstat().st_mode):
                raise _prepare_error("SOURCE_PATH_UNSAFE", location, "candidate paths may not contain symlinks")
        except OSError as exc:
            raise _prepare_error("SOURCE_PATH_UNSAFE", location, "the candidate path cannot be inspected safely") from exc
    return relative.as_posix(), candidate


def _read_regular(path: Path, location: str) -> tuple[bytes, str]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "the declared source file is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "source must be a regular, non-symlink, non-hardlinked file")
    try:
        content = path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "the source bytes cannot be read safely") from exc
    return content, _sha256_bytes(content)


def _ensure_internal_parent(root: Path, relative: Path, location: str) -> Path:
    """Create only missing candidate directories after checking every parent."""
    internal_root = root.expanduser().resolve(strict=False)
    internal_root.mkdir(parents=True, exist_ok=True)
    current = internal_root
    for part in relative.parts:
        current = current / part
        try:
            if current.exists() and current.is_symlink():
                raise _prepare_error("SOURCE_PATH_UNSAFE", location, "candidate directories may not contain symlinks")
            if current.exists() and not current.is_dir():
                raise _prepare_error("CANDIDATE_CONFLICT", location, "candidate path is occupied by a non-directory")
            current.mkdir(exist_ok=True)
        except OSError as exc:
            raise _prepare_error("CANDIDATE_WRITE_FAILED", location, "create the internal candidate directory and retry") from exc
    return current


def _write_create_only(root: Path, locator: str, content: bytes) -> bool:
    relative, candidate = _candidate_locator(root, locator, locator)
    if candidate.exists() or candidate.is_symlink():
        existing, _ = _read_regular(candidate, locator)
        if existing != content:
            raise _prepare_error("CANDIDATE_CONFLICT", locator, "use prepare --refresh for an intentional candidate edit; do not overwrite bytes")
        return False
    _ensure_internal_parent(root, Path(relative).parent, locator)
    try:
        with candidate.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        existing, _ = _read_regular(candidate, locator)
        if existing != content:
            raise _prepare_error("CANDIDATE_CONFLICT", locator, "do not overwrite a concurrently created candidate")
        return False
    except OSError as exc:
        raise _prepare_error("CANDIDATE_WRITE_FAILED", locator, "repair the internal candidate directory and retry") from exc
    return True


def _write_refresh(root: Path, locator: str, content: bytes) -> None:
    _, target = _internal_locator(root, locator, locator)
    _ensure_internal_parent(root, Path(locator).parent, locator)
    if target.is_symlink():
        raise _prepare_error("SOURCE_PATH_UNSAFE", locator, "the request file may not be a symlink")
    try:
        if target.lstat().st_nlink != 1:
            raise _prepare_error("SOURCE_PATH_UNSAFE", locator, "the request file may not be hardlinked")
    except OSError as exc:
        raise _prepare_error("SOURCE_PATH_UNSAFE", locator, "the request file cannot be inspected safely") from exc
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        raise _prepare_error("CANDIDATE_WRITE_FAILED", locator, "refresh the internal request atomically after repairing access") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _request_yaml_bytes(request: Mapping[str, object]) -> bytes:
    return yaml.dump(
        dict(request),
        Dumper=_QuotedStringDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        # Project's native flat YAML readers require each scalar on one line.
        # Wrapping the JSON asset manifest produces an unreadable catalog.
        width=2_147_483_647,
    ).encode("utf-8")


def _resolution_root(resolution: object, run_id: str, location: str) -> Path:
    errors = validate_destination_resolution(resolution, location)
    if errors or not isinstance(resolution, Mapping):
        raise _prepare_error("DESTINATION_INVALID", location, "supply destination-resolution/v1 from the shared resolver")
    if resolution.get("run_id") != run_id:
        raise _prepare_error("DESTINATION_INVALID", location, "the resolution run_id must match the source report")
    destinations = resolution.get("destinations")
    internal = destinations.get("internal_output_root") if isinstance(destinations, Mapping) else None
    path = internal.get("path") if isinstance(internal, Mapping) else None
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise _prepare_error("DESTINATION_INVALID", location, "resolution must declare an absolute internal_output_root")
    return Path(path).expanduser().resolve(strict=False)


def _prepare_resolution(destinations_file: str | Path, run_id: str) -> tuple[dict[str, object], Path]:
    try:
        from tools.workspace import load_manifest

        manifest = load_manifest()
        resolution = resolve_destinations(
            destinations_file,
            repository_root=ROOT,
            child_roots=manifest_child_roots(manifest, ROOT / "repos"),
            run_id=run_id,
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        raise _prepare_error("DESTINATION_INVALID", "destinations-file", "repair the external output-destinations profile") from exc
    return resolution, _resolution_root(resolution, run_id, "destination-resolution")


def _projection_resolution(
    destinations_file: str | Path,
    context_id: str,
    *,
    target_root: Path | None = None,
) -> dict[str, object]:
    """Resolve profile roles, allowing only the declared target-root override."""
    try:
        from tools.workspace import load_manifest

        manifest = load_manifest()
        direct = {"public_projection_root": str(target_root)} if target_root is not None else None
        return resolve_destinations(
            destinations_file,
            direct=direct,
            repository_root=ROOT,
            child_roots=manifest_child_roots(manifest, ROOT / "repos"),
            run_id=context_id,
            project_id=context_id,
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        raise _prepare_error("DESTINATION_INVALID", "destinations-file", "repair the selected external output-destinations profile") from exc


def _resolution_role(resolution: Mapping[str, object], role: str) -> Path:
    destinations = resolution.get("destinations")
    item = destinations.get(role) if isinstance(destinations, Mapping) else None
    path = item.get("path") if isinstance(item, Mapping) else None
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise _prepare_error("DESTINATION_INVALID", role, "the selected profile must resolve this destination role")
    return Path(path).expanduser().resolve(strict=False)


def _assert_report_resolution(report: Mapping[str, object], root: Path, run_id: str) -> None:
    report_resolution = report.get("destination_resolution")
    report_root = _resolution_root(report_resolution, run_id, "source.destination_resolution")
    if report_root != root.expanduser().resolve(strict=False):
        raise _prepare_error("DESTINATION_MISMATCH", "source.destination_resolution", "use the same internal_output_root profile that produced the source report")


def _candidate_root(root: Path, projection_id: str) -> tuple[str, Path]:
    if STABLE_ID.fullmatch(projection_id) is None:
        raise _prepare_error("PROJECTION_ID_INVALID", "projection_id", "use the declared stable projection identifier")
    relative = Path(PREPARE_ROOT) / _path_token(projection_id)
    return relative.as_posix(), root.expanduser().resolve(strict=False) / relative


def _source_metadata(
    report: Mapping[str, object],
    *,
    default_run_id: str,
    location: str,
) -> tuple[str, str, str]:
    run_id = report.get("run_id", default_run_id)
    if not isinstance(run_id, str) or STABLE_ID.fullmatch(run_id) is None:
        raise _prepare_error("PROVENANCE_MISSING", f"{location}.run_id", "retain a stable source run_id")
    repository = report.get("production_repository", PRODUCTION_REPOSITORY)
    commit = report.get("production_source_commit", report.get("source_commit"))
    if not _valid_repo_id(repository) or not _valid_commit(commit):
        raise _prepare_error("PROVENANCE_MISSING", f"{location}.commit", "retain the production repository and its 40-hex source commit")
    return str(repository), str(commit), run_id


def _record_spec(
    *,
    root: Path,
    candidate_relative_root: str,
    record_kind: str,
    slug: str,
    title: str,
    source_path: object,
    canonical_sha256: object,
    repository: str,
    commit: str,
    run_id: str,
    index: int,
    automatic_plan: bool = False,
) -> tuple[dict[str, object], str, bytes]:
    if record_kind not in {"plan", "work"}:
        raise _prepare_error("SOURCE_UNAVAILABLE", f"records[{index}]", "prepare only a declared plan or an available work manifest")
    if automatic_plan and record_kind != "plan":
        raise _prepare_error("AUTHORITY_INVALID", f"records[{index}].record_kind", "the automatic projection authority is restricted to production plans")
    if not isinstance(slug, str) or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) is None:
        raise _prepare_error("PROVENANCE_MISSING", f"records[{index}].slug", "retain a lowercase hyphenated source slug")
    if not isinstance(title, str) or not title.strip():
        raise _prepare_error("PROVENANCE_MISSING", f"records[{index}].title", "retain a non-empty source title")
    if not isinstance(canonical_sha256, str) or HASH64.fullmatch(canonical_sha256) is None:
        raise _prepare_error("PROVENANCE_MISSING", f"records[{index}].canonical_sha256", "retain the declared canonical artifact SHA-256")
    source_locator, source_file = _source_locator(root, source_path, f"records[{index}].source")
    content, actual_hash = _read_regular(source_file, source_locator)
    if actual_hash != canonical_sha256:
        raise _prepare_error("SOURCE_HASH_MISMATCH", f"records[{index}].source", "regenerate the source report from the unchanged canonical plan")
    try:
        body_text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _prepare_error("FORBIDDEN_CONTENT", f"records[{index}].body", "production-plan.md must be UTF-8 Markdown") from exc
    security_findings = scan_public_projection(body_text, f"records[{index}].body")
    if security_findings:
        first = sorted(security_findings, key=lambda finding: (finding.get("code", ""), finding.get("location", "")))[0]
        raise _prepare_error(str(first["code"]), f"records[{index}].body", "edit the internal candidate through an approved public-ready workflow before projection")
    body_name = "plan.md" if record_kind == "plan" else "record.md"
    source_key = f"{record_kind}-{canonical_sha256}"
    candidate_locator = f"{candidate_relative_root}/records/{source_key}/{body_name}"
    file_entry = {
        "role": "body",
        "source_locator": candidate_locator,
        "target_locator": body_name,
        "sha256": actual_hash,
        "mime_type": "text/markdown",
        "rights_status": "cleared" if automatic_plan else "unknown",
    }
    record: dict[str, object] = {
        "record_kind": record_kind,
        "slug": slug,
        "title": title,
        "source": {
            "repository": repository,
            "commit": commit,
            "run_id": run_id,
            "locator": source_locator,
            "canonical_sha256": canonical_sha256,
            "sha256": record_file_sha256([file_entry]),
        },
        "publication": {
            "visibility": "public" if automatic_plan else "unknown",
            "rights_status": "cleared" if automatic_plan else "unknown",
            "consent_status": "cleared" if automatic_plan else "unknown",
            "attribution": [],
        },
        "files": [file_entry],
    }
    return record, candidate_locator, content


def _security_request_findings(request: Mapping[str, object]) -> list[dict[str, str]]:
    return [
        finding for finding in request_policy_findings(request)
        if finding.get("code") not in {"UNKNOWN_CLEARANCE", "UNAPPROVED_MEDIA"}
    ]


def _load_existing_request(path: Path, expected: Mapping[str, object], root: Path) -> dict[str, object] | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        raise _prepare_error("SOURCE_PATH_UNSAFE", "request.yaml", "the candidate request may not be a symlink")
    try:
        existing = _load_document(path)
    except PublicProjectionError as exc:
        raise _prepare_error("CANDIDATE_CONFLICT", "request.yaml", "repair or archive the invalid candidate request and use a new projection ID") from exc
    if not isinstance(existing, Mapping) or validate_request(existing):
        raise _prepare_error("CANDIDATE_CONFLICT", "request.yaml", "repair or archive the invalid candidate request and use a new projection ID")
    if request_sha256(existing) != request_sha256(expected):
        raise _prepare_error("CANDIDATE_CONFLICT", "request.yaml", "use a new projection ID; existing candidate bytes are immutable")
    for record_index, record in enumerate(existing.get("records", [])):
        if not isinstance(record, Mapping):
            continue
        files = record.get("files", [])
        if not isinstance(files, list):
            continue
        for file_index, file in enumerate(files):
            if not isinstance(file, Mapping):
                continue
            _, candidate = _internal_locator(root, file.get("source_locator"), f"records[{record_index}].files[{file_index}]")
            content, actual_hash = _read_regular(candidate, f"records[{record_index}].files[{file_index}]")
            if actual_hash != file.get("sha256"):
                raise _prepare_error("CANDIDATE_DRIFT", f"records[{record_index}].files[{file_index}]", "run prepare --refresh before planning projection")
            if file.get("role") == "body":
                try:
                    body_text = content.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise _prepare_error("FORBIDDEN_CONTENT", f"records[{record_index}].files[{file_index}]", "body files must remain UTF-8 Markdown") from exc
                findings = scan_public_projection(body_text, f"records[{record_index}].files[{file_index}]")
                if findings:
                    first = sorted(findings, key=lambda finding: (finding.get("code", ""), finding.get("location", "")))[0]
                    raise _prepare_error(str(first["code"]), f"records[{record_index}].files[{file_index}]", "remove unsafe candidate content before projection")
    return dict(existing)


def _write_candidate_request(root: Path, projection_id: str, request: Mapping[str, object], payloads: list[tuple[str, bytes]]) -> dict[str, object]:
    candidate_relative_root, _ = _candidate_root(root, projection_id)
    request_locator = f"{candidate_relative_root}/request.yaml"
    request_path = root.expanduser().resolve(strict=False) / request_locator
    expected_hash = request_sha256(request)
    existing = _load_existing_request(request_path, request, root)
    if existing is not None:
        return {
            "command": "prepare",
            "status": "ALREADY_PREPARED",
            "projection_id": projection_id,
            "record_count": len(existing.get("records", [])),
            "request_locator": request_locator,
            "finding_codes": [],
            "work_status": "NOT_AVAILABLE",
            "request_sha256": expected_hash,
        }
    for locator, content in payloads:
        # All payloads are prevalidated before the first candidate write.
        existing_path = root.expanduser().resolve(strict=False) / locator
        if existing_path.exists() or existing_path.is_symlink():
            current, _ = _read_regular(existing_path, locator)
            if current != content:
                raise _prepare_error("CANDIDATE_CONFLICT", locator, "use a new projection ID or refresh the candidate explicitly")
    for locator, content in payloads:
        _write_create_only(root, locator, content)
    _write_create_only(root, request_locator, _request_yaml_bytes(request))
    return {
        "command": "prepare",
        "status": "PASSED",
        "projection_id": projection_id,
        "record_count": len(request["records"]),
        "request_locator": request_locator,
        "finding_codes": [],
        "work_status": "NOT_AVAILABLE",
        "request_sha256": expected_hash,
    }


def _build_request(
    *,
    root: Path,
    projection_id: str,
    generated_at: str,
    source_specs: list[tuple[str, str, str, object, object, str, str, str]],
    automatic_plan: bool = False,
) -> tuple[dict[str, object], list[tuple[str, bytes]]]:
    if not _valid_timestamp(generated_at):
        raise _prepare_error("PROVENANCE_MISSING", "generated_at", "retain an RFC3339 timestamp from the completed source run")
    candidate_relative_root, _ = _candidate_root(root, projection_id)
    records: list[dict[str, object]] = []
    payloads: list[tuple[str, bytes]] = []
    seen_keys: set[str] = set()
    for index, (kind, slug, title, path, canonical, repository, commit, run_id) in enumerate(source_specs):
        record, locator, content = _record_spec(
            root=root,
            candidate_relative_root=candidate_relative_root,
            record_kind=kind,
            slug=slug,
            title=title,
            source_path=path,
            canonical_sha256=canonical,
            repository=repository,
            commit=commit,
            run_id=run_id,
            index=index,
            automatic_plan=automatic_plan,
        )
        source_key = f"{kind}-{record['source']['canonical_sha256']}"
        if source_key in seen_keys:
            continue
        seen_keys.add(source_key)
        records.append(record)
        payloads.append((locator, content))
    records.sort(key=lambda record: (str(record["record_kind"]), str(record["source"]["canonical_sha256"]), str(record["slug"])))
    payloads.sort(key=lambda item: item[0])
    if not records:
        raise _prepare_error("SOURCE_UNAVAILABLE", "records", "retain at least one completed production plan; do not invent a work record")
    request: dict[str, object] = {
        "contract_version": "public-projection-request/v1",
        "projection_id": projection_id,
        "generated_at": generated_at,
        "source_root_role": "internal_output_root",
        "records": records,
    }
    structural = validate_request(request)
    if structural:
        raise _prepare_error("REQUEST_INVALID", "request", "regenerate the candidate from a valid public-projection-request/v1 source")
    security = _security_request_findings(request)
    if security:
        first = sorted(security, key=lambda finding: (finding.get("code", ""), finding.get("location", "")))[0]
        raise _prepare_error(str(first["code"]), str(first.get("location", "request")), "remove the unsafe metadata before projection")
    return request, payloads


def prepare_run_report(
    report: Mapping[str, object],
    *,
    internal_output_root: Path,
    projection_id: str | None = None,
    automatic_plan: bool = False,
) -> dict[str, object]:
    """Produce one internal request from a completed PLAN_READY run.

    The public CLI uses the default draft mode.  ``automatic_plan`` is an
    internal producer-only mode used by the canonical run entrypoint and
    marks a plan as public-by-construction; it is never exposed as a free-form
    CLI request option.
    """
    if not isinstance(report, Mapping):
        raise _prepare_error("SOURCE_INVALID", "run-report", "provide a JSON object source report")
    projection_id = projection_id or str(report.get("run_id", ""))
    run_id = report.get("run_id")
    if not isinstance(run_id, str) or STABLE_ID.fullmatch(run_id) is None:
        raise _prepare_error("PROVENANCE_MISSING", "run_id", "retain the stable run identifier")
    if report.get("status") != "PLAN_READY":
        return {
            "command": "prepare",
            "status": "NOT_AVAILABLE",
            "projection_id": projection_id,
            "record_count": 0,
            "request_locator": None,
            "finding_codes": [],
            "work_status": "NOT_AVAILABLE",
        }
    _assert_report_resolution(report, internal_output_root, run_id)
    repository, commit, source_run_id = _source_metadata(report, default_run_id=run_id, location="run-report")
    generated_at = report.get("generated_at", report.get("requested_at"))
    slug = report.get("project_slug")
    source_path = report.get("plan")
    if not isinstance(slug, str) and isinstance(source_path, str):
        parts = Path(source_path).parts
        if len(parts) >= 3:
            slug = parts[-3]
    title = report.get("project_title", report.get("title", slug))
    request, payloads = _build_request(
        root=internal_output_root,
        projection_id=projection_id,
        generated_at=str(generated_at) if generated_at is not None else "",
        source_specs=[("plan", str(slug), str(title), source_path, report.get("production_plan_sha256"), repository, commit, source_run_id)],
        automatic_plan=automatic_plan,
    )
    return _write_candidate_request(internal_output_root, projection_id, request, payloads)


def _batch_source_specs(summary: Mapping[str, object], root: Path) -> list[tuple[str, str, str, object, object, str, str, str]]:
    run_id = summary.get("run_id")
    output_locator = summary.get("output_root_locator")
    projects = summary.get("projects")
    if not isinstance(run_id, str) or STABLE_ID.fullmatch(run_id) is None:
        raise _prepare_error("PROVENANCE_MISSING", "batch.run_id", "retain the stable batch run identifier")
    if not isinstance(output_locator, str):
        raise _prepare_error("PROVENANCE_MISSING", "batch.output_root_locator", "record the internal batch output locator")
    output_relative, output_root = _internal_locator(root, output_locator, "batch.output_root_locator", allow_dot=True)
    if not isinstance(projects, list):
        raise _prepare_error("SOURCE_UNAVAILABLE", "batch.projects", "retain the completed project summaries")
    specs: list[tuple[str, str, str, object, object, str, str, str]] = []
    for index, project in enumerate(sorted((item for item in projects if isinstance(item, Mapping)), key=lambda item: str(item.get("project_id", "")))):
        project_id = project.get("project_id")
        if project.get("status") != "PASSED":
            continue
        if not isinstance(project_id, str) or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", project_id) is None:
            raise _prepare_error("PROVENANCE_MISSING", f"batch.projects[{index}].project_id", "retain a safe completed project id")
        expected_locator = f"run://{run_id}/production/{project_id}"
        if project.get("production_locator") != expected_locator:
            raise _prepare_error("PROVENANCE_MISSING", f"batch.projects[{index}].production_locator", "preserve the batch production locator")
        repository = project.get("production_repository", PRODUCTION_REPOSITORY)
        commit = project.get("production_source_commit")
        if not _valid_repo_id(repository) or not _valid_commit(commit):
            raise _prepare_error("PROVENANCE_MISSING", f"batch.projects[{index}].production_source_commit", "retain the production repository and source commit")
        source_path = root / output_relative / "production" / project_id / "03_plan" / "production-plan.md"
        specs.append((
            "plan", project_id, str(project.get("title", project_id)), source_path,
            project.get("production_plan_markdown_sha256"), str(repository), str(commit), run_id,
        ))
    return specs


def prepare_batch_summary(
    summary: Mapping[str, object],
    *,
    internal_output_root: Path,
    projection_id: str | None = None,
    automatic_plan: bool = False,
) -> dict[str, object]:
    """Produce one deterministic internal request from a PASSED batch."""
    if not isinstance(summary, Mapping):
        raise _prepare_error("SOURCE_INVALID", "batch-summary", "provide a JSON object source summary")
    projection_id = projection_id or str(summary.get("run_id", ""))
    run_id = summary.get("run_id")
    if not isinstance(run_id, str) or STABLE_ID.fullmatch(run_id) is None:
        raise _prepare_error("PROVENANCE_MISSING", "batch.run_id", "retain the stable batch identifier")
    if summary.get("status") != "PASSED":
        return {
            "command": "prepare",
            "status": "NOT_AVAILABLE",
            "projection_id": projection_id,
            "record_count": 0,
            "request_locator": None,
            "finding_codes": [],
            "work_status": "NOT_AVAILABLE",
        }
    resolved_root = _resolution_root(summary.get("destination_resolution"), run_id, "batch.destination_resolution")
    if resolved_root != internal_output_root.expanduser().resolve(strict=False):
        raise _prepare_error("DESTINATION_MISMATCH", "batch.destination_resolution", "use the same internal_output_root profile that produced the source summary")
    specs = _batch_source_specs(summary, internal_output_root)
    request, payloads = _build_request(
        root=internal_output_root,
        projection_id=projection_id,
        generated_at=str(summary.get("generated_at", "")),
        source_specs=specs,
        automatic_plan=automatic_plan,
    )
    return _write_candidate_request(internal_output_root, projection_id, request, payloads)


def refresh_request(request_path: Path, *, internal_output_root: Path) -> dict[str, object]:
    """Rehash candidate files while preserving canonical provenance and clearance."""
    locator, resolved_request = _source_locator(internal_output_root, str(request_path), "refresh.request")
    if not locator.startswith(f"{PREPARE_ROOT}/") or not locator.endswith("/request.yaml"):
        raise _prepare_error("SOURCE_PATH_UNSAFE", "refresh.request", "refresh only an internal public-projection-candidates request")
    request = _load_document(resolved_request)
    if not isinstance(request, Mapping):
        raise _prepare_error("REQUEST_INVALID", "refresh.request", "provide a public-projection-request/v1 mapping")
    errors = validate_request(request)
    if errors:
        raise _prepare_error("REQUEST_INVALID", "refresh.request", "repair the request contract before refreshing candidate hashes")
    refreshed = deepcopy(dict(request))
    for record_index, record in enumerate(refreshed.get("records", [])):
        if not isinstance(record, Mapping):
            continue
        files = record.get("files")
        if not isinstance(files, list):
            continue
        refreshed_files: list[dict[str, object]] = []
        for file_index, file in enumerate(files):
            if not isinstance(file, Mapping):
                continue
            _, candidate = _internal_locator(internal_output_root, file.get("source_locator"), f"records[{record_index}].files[{file_index}]")
            content, actual_hash = _read_regular(candidate, f"records[{record_index}].files[{file_index}]")
            if file.get("role") in {"body", "readme", "process"}:
                try:
                    text_content = content.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise _prepare_error("FORBIDDEN_CONTENT", f"records[{record_index}].files[{file_index}]", "text candidate files must remain UTF-8") from exc
                findings = scan_public_projection(text_content, f"records[{record_index}].files[{file_index}]")
                if findings:
                    first = sorted(findings, key=lambda finding: (finding.get("code", ""), finding.get("location", "")))[0]
                    raise _prepare_error(str(first["code"]), f"records[{record_index}].files[{file_index}]", "remove unsafe candidate content before projection")
            changed = dict(file)
            changed["sha256"] = actual_hash
            refreshed_files.append(changed)
        changed_record = dict(record)
        changed_record["files"] = refreshed_files
        source = dict(record["source"])
        source["sha256"] = record_file_sha256(refreshed_files)
        # canonical_sha256, publication, and every provenance field remain untouched.
        changed_record["source"] = source
        refreshed["records"][record_index] = changed_record
    structural = validate_request(refreshed)
    if structural:
        raise _prepare_error("REQUEST_INVALID", "refresh.request", "recalculated file hashes do not form a valid request")
    security = _security_request_findings(refreshed)
    if security:
        first = sorted(security, key=lambda finding: (finding.get("code", ""), finding.get("location", "")))[0]
        raise _prepare_error(str(first["code"]), str(first.get("location", "refresh.request")), "remove unsafe metadata before projection")
    before = request_sha256(request)
    after = request_sha256(refreshed)
    if before != after:
        _write_refresh(internal_output_root, locator, _request_yaml_bytes(refreshed))
    return {
        "command": "prepare",
        "status": "REFRESHED",
        "projection_id": str(refreshed["projection_id"]),
        "record_count": len(refreshed["records"]),
        "request_locator": locator,
        "finding_codes": [],
        "work_status": "NOT_AVAILABLE",
        "request_sha256": after,
    }


def _projection_finding(code: str, location: str, remediation: str) -> dict[str, str]:
    """Build a result finding without copying source values into evidence."""
    if code not in PUBLIC_PROJECTION_FINDING_CODES:
        code = "LAYOUT_INVALID"
    return {"code": code, "location": location, "remediation": remediation}


def _dedupe_projection_findings(findings: list[Mapping[str, object]]) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        code = str(finding.get("code", "LAYOUT_INVALID"))
        location = str(finding.get("location", "projection"))
        remediation = str(finding.get("remediation", "repair the public projection input"))
        safe = _projection_finding(code, location, remediation)
        unique[json.dumps(safe, ensure_ascii=False, sort_keys=True)] = safe
    return [unique[key] for key in sorted(unique)]


def _target_locator(root: Path, raw: object, location: str) -> tuple[str, Path]:
    """Resolve one target-relative path without following aliases."""
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute() or "\\" in raw:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "use a normalized relative target locator")
    parts = Path(raw).parts
    if any(part in {"", ".", ".."} for part in parts) or RELATIVE_PATH.fullmatch(raw) is None:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "use a normalized relative target locator without traversal")
    relative = Path(raw)
    target_root = root.expanduser().resolve(strict=False)
    candidate = target_root / relative
    try:
        candidate.resolve(strict=False).relative_to(target_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _prepare_error("SOURCE_PATH_UNSAFE", location, "keep the target locator below public_projection_root") from exc
    probe = target_root
    for part in relative.parts:
        probe = probe / part
        try:
            if stat.S_ISLNK(probe.lstat().st_mode):
                raise _prepare_error("SOURCE_PATH_UNSAFE", location, "target paths may not contain symlinks")
        except FileNotFoundError:
            break
        except OSError as exc:
            raise _prepare_error("SOURCE_PATH_UNSAFE", location, "the target path cannot be inspected safely") from exc
    return relative.as_posix(), candidate


def _target_regular(path: Path, location: str) -> tuple[bytes, str]:
    """Read one existing target file while rejecting aliases and special files."""
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise _prepare_error("LAYOUT_INVALID", location, "the target file is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise _prepare_error("LAYOUT_INVALID", location, "target files must be regular, non-symlink, non-hardlinked files")
    try:
        content = path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise _prepare_error("LAYOUT_INVALID", location, "the target file cannot be read safely") from exc
    return content, _sha256_bytes(content)


def _git_target_findings(target: Path) -> list[dict[str, str]]:
    """Inspect a target worktree without fetch, checkout, or other Git mutation."""
    findings: list[dict[str, str]] = []
    target = target.expanduser().resolve(strict=False)
    if not target.exists() or not target.is_dir() or target.is_symlink():
        return [_projection_finding("LAYOUT_INVALID", "target.root", "provide an existing local Git worktree")]

    def run_git(*arguments: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                ["git", *arguments],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None

    root_result = run_git("rev-parse", "--show-toplevel")
    if root_result is None or root_result.returncode != 0:
        findings.append(_projection_finding("LAYOUT_INVALID", "target.git", "initialize or select a local Git worktree before projection"))
    else:
        try:
            observed_root = Path(root_result.stdout.strip()).expanduser().resolve(strict=False)
        except (OSError, RuntimeError):
            observed_root = None
        if observed_root != target:
            findings.append(_projection_finding("LAYOUT_INVALID", "target.git", "the public projection root must be the worktree root"))

    branch_result = run_git("symbolic-ref", "--quiet", "--short", "HEAD")
    if branch_result is None or branch_result.returncode != 0 or not branch_result.stdout.strip():
        findings.append(_projection_finding("LAYOUT_INVALID", "target.git", "use a non-detached local worktree branch"))

    status_result = run_git("status", "--porcelain=v1", "--untracked-files=all")
    if status_result is None or status_result.returncode != 0:
        findings.append(_projection_finding("LAYOUT_INVALID", "target.git", "the target Git status must be inspectable without remote access"))
    elif status_result.stdout:
        findings.append(_projection_finding("TARGET_DIRTY", "target.git", "commit or otherwise manually resolve existing target changes before planning"))
    return _dedupe_projection_findings(findings)


def _git_target_status_paths(target: Path) -> list[str] | None:
    """Return porcelain paths for a replay check; never expose Git output."""
    target = target.expanduser().resolve(strict=False)
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=target,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    paths: list[str] = []
    for line in completed.stdout.splitlines():
        if not line:
            continue
        if len(line) < 4:
            return None
        path = line[3:]
        # Renames contain two paths and are never a safe replay signal.  The
        # public layout itself only permits ASCII relative path tokens.
        if " -> " in path or Path(path).is_absolute() or RELATIVE_PATH.fullmatch(path) is None:
            return None
        paths.append(Path(path).as_posix())
    return sorted(set(paths))


def _tree_fingerprint(root: Path) -> str:
    """Hash target file identities and bytes while excluding Git internals."""
    root = root.expanduser().resolve(strict=False)
    descriptors: list[dict[str, object]] = []
    if not root.exists():
        return sha256_hex(descriptors)
    if root.is_symlink() or not root.is_dir():
        raise _prepare_error("LAYOUT_INVALID", "target.root", "the target root must be a directory")
    try:
        paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
        for path in paths:
            relative = path.relative_to(root)
            if ".git" in relative.parts:
                continue
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) and not stat.S_ISDIR(metadata.st_mode):
                raise _prepare_error("LAYOUT_INVALID", "target.tree", "the target contains an unsupported alias or special file")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if metadata.st_nlink != 1:
                raise _prepare_error("LAYOUT_INVALID", "target.tree", "target files may not be hardlinked")
            content = path.read_bytes()
            descriptors.append({"path": relative.as_posix(), "sha256": _sha256_bytes(content), "size": len(content)})
    except (OSError, UnicodeError) as exc:
        raise _prepare_error("LAYOUT_INVALID", "target.tree", "the target fingerprint cannot be computed safely") from exc
    return sha256_hex(descriptors)


def _layout_collections(layout: Mapping[str, object], location: str = "layout.collections") -> tuple[str, str]:
    collections = layout.get("collections")
    if not isinstance(collections, Mapping):
        raise _prepare_error("LAYOUT_INVALID", location, "declare plans and works collection paths")
    values: list[str] = []
    for name in ("plans", "works"):
        value = collections.get(name)
        if not isinstance(value, str) or any(part in {".", ".."} for part in Path(value).parts) or RELATIVE_PATH.fullmatch(value) is None:
            raise _prepare_error("LAYOUT_INVALID", f"{location}.{name}", "use a distinct normalized relative collection path")
        values.append(value)
    if values[0] == values[1] or values[0].startswith(values[1] + "/") or values[1].startswith(values[0] + "/"):
        raise _prepare_error("LAYOUT_INVALID", location, "plans and works collections may not overlap")
    markers = layout.get("catalog_markers")
    if not isinstance(markers, Mapping) or not isinstance(markers.get("start"), str) or not isinstance(markers.get("end"), str):
        raise _prepare_error("LAYOUT_INVALID", "layout.catalog_markers", "declare one non-empty catalog marker pair")
    if markers["start"] == markers["end"]:
        raise _prepare_error("LAYOUT_INVALID", "layout.catalog_markers", "catalog start and end markers must differ")
    return values[0], values[1]


def _load_target_document(target: Path, relative: str, location: str) -> object:
    _, path = _target_locator(target, relative, location)
    content, _ = _target_regular(path, location)
    try:
        return yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise _prepare_error("LAYOUT_INVALID", location, "repair the target UTF-8 YAML document") from exc


def _marker_block(text: str, layout: Mapping[str, object], location: str) -> tuple[int, int]:
    markers = layout.get("catalog_markers")
    if not isinstance(markers, Mapping):
        raise _prepare_error("LAYOUT_INVALID", location, "declare catalog markers in public-project.yaml")
    start = markers.get("start")
    end = markers.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise _prepare_error("LAYOUT_INVALID", location, "declare string catalog markers")
    start_count = text.count(start)
    end_count = text.count(end)
    start_at = text.find(start)
    end_at = text.find(end)
    if start_count != 1 or end_count != 1 or start_at < 0 or end_at < 0 or start_at >= end_at:
        raise _prepare_error("LAYOUT_INVALID", location, "each collection README must contain exactly one ordered marker pair")
    return start_at, end_at


def _append_marker_block(text: str, layout: Mapping[str, object]) -> str:
    markers = layout["catalog_markers"]
    start = str(markers["start"])
    end = str(markers["end"])
    prefix = "" if not text or text.endswith("\n") else "\n"
    return f"{text}{prefix}{start}\n{end}\n"


def _replace_marker_block(text: str, layout: Mapping[str, object], body: str, location: str) -> str:
    start_at, end_at = _marker_block(text, layout, location)
    markers = layout["catalog_markers"]
    start = str(markers["start"])
    end = str(markers["end"])
    before = text[:start_at]
    after = text[end_at + len(end):]
    if after and not after.startswith("\n"):
        body_suffix = "\n"
    else:
        body_suffix = ""
    inner = f"{body}\n" if body else ""
    return f"{before}{start}\n{inner}{end}{body_suffix}{after}"


def _root_catalog_update(
    target: Path,
    layout: Mapping[str, object],
    plans_index: Mapping[str, object],
) -> tuple[bytes, bytes] | None:
    """Return a root README replacement when the target opts into root links.

    Older public targets may not have a root catalog block, so the feature is
    opt-in by the presence of the existing layout marker pair.  The current
    ``agentic-art-project`` target contains the pair and therefore receives a
    deterministic list of links rooted at ``plans/``.
    """

    root = target / "README.md"
    if not root.exists() or root.is_symlink():
        return None
    current, _ = _target_regular(root, "target.root.README")
    try:
        text = current.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _prepare_error("LAYOUT_INVALID", "target.root.README", "root README must remain UTF-8") from exc
    markers = layout.get("catalog_markers")
    if not isinstance(markers, Mapping):
        raise _prepare_error("LAYOUT_INVALID", "layout.catalog_markers", "declare catalog markers in public-project.yaml")
    start = markers.get("start")
    end = markers.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise _prepare_error("LAYOUT_INVALID", "layout.catalog_markers", "declare string catalog markers")
    starts = text.count(start)
    ends = text.count(end)
    if starts == 0 and ends == 0:
        return None
    if starts != 1 or ends != 1 or text.find(start) >= text.find(end):
        raise _prepare_error(
            "LAYOUT_INVALID",
            "target.root.README",
            "root README catalog markers must be one ordered pair or both absent",
        )
    desired = _replace_marker_block(
        text,
        layout,
        _catalog_text(plans_index, "plans", root=True),
        "target.root.README",
    ).encode("utf-8")
    return current, desired


def _index_scaffold_bytes() -> bytes:
    return b"version: 1\nrecords: []\nretired_ids: []\n"


def _layout_bytes(layout: Mapping[str, object]) -> bytes:
    return _request_yaml_bytes(layout)


def _validate_index_path(collection: str, raw: object, location: str) -> str:
    if raw is None:
        raise _prepare_error("LAYOUT_INVALID", location, "each index record must declare its public directory path")
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute() or "\\" in raw or any(part in {".", ".."} for part in Path(raw).parts) or RELATIVE_PATH.fullmatch(raw) is None:
        raise _prepare_error("LAYOUT_INVALID", location, "index paths must be normalized relative paths")
    relative = Path(raw).as_posix()
    if relative.startswith(collection + "/"):
        normalized = relative
    elif "/" not in relative:
        normalized = f"{collection}/{relative}"
    else:
        raise _prepare_error("LAYOUT_INVALID", location, "index record paths must remain directly below their collection")
    directory = Path(normalized)
    if directory.parent.as_posix() != collection:
        raise _prepare_error("LAYOUT_INVALID", location, "index record paths must name one collection child directory")
    return normalized


INDEX_ALLOWED_KEYS = {"id", "slug", "title", "path", "source_key", "source_ref", "content_sha256", "status", "visibility", "rights_status"}


def _load_target_index(target: Path, collection: str, prefix: str, location: str) -> dict[str, object]:
    relative = f"{collection}/index.yaml"
    document = _load_target_document(target, relative, location)
    if not isinstance(document, Mapping) or document.get("version") != INDEX_VERSION:
        raise _prepare_error("LAYOUT_INVALID", location, "use the public projection index version 1")
    records = document.get("records")
    retired = document.get("retired_ids", [])
    if not isinstance(records, list) or not isinstance(retired, list):
        raise _prepare_error("LAYOUT_INVALID", location, "index records and retired_ids must be lists")
    security = scan_public_projection(document, location)
    if security:
        raise _prepare_error("FORBIDDEN_CONTENT", location, "remove internal references or credentials from the public index")
    normalized: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    seen_paths: set[str] = set()
    retired_ids: set[str] = set()
    for index, value in enumerate(retired):
        if not isinstance(value, str) or re.fullmatch(rf"{prefix}[0-9]{{4}}", value) is None or value in retired_ids:
            raise _prepare_error("LAYOUT_INVALID", f"{location}.retired_ids[{index}]", "retired IDs must be unique four-digit public IDs")
        retired_ids.add(value)
    for index, value in enumerate(records):
        if not isinstance(value, Mapping) or set(value) - INDEX_ALLOWED_KEYS:
            raise _prepare_error("LAYOUT_INVALID", f"{location}.records[{index}]", "index records may contain only public metadata fields")
        public_id = value.get("id")
        if not isinstance(public_id, str) or re.fullmatch(rf"{prefix}[0-9]{{4}}", public_id) is None or public_id in seen_ids or public_id in retired_ids:
            raise _prepare_error("LAYOUT_INVALID", f"{location}.records[{index}].id", "active public IDs must be unique and not retired")
        source_key = value.get("source_key")
        if source_key is None and isinstance(value.get("source_ref"), str) and value["source_ref"].startswith("sha256:"):
            source_key = f"{'plan' if prefix == 'P' else 'work'}:{value['source_ref'][len('sha256:'):]}"
        if not isinstance(source_key, str) or not re.fullmatch(rf"{'plan' if prefix == 'P' else 'work'}:[0-9a-f]{{64}}", source_key) or source_key in seen_sources:
            raise _prepare_error("LAYOUT_INVALID", f"{location}.records[{index}].source_key", "source keys must be unique opaque kind/hash values")
        content_sha256 = value.get("content_sha256")
        if not isinstance(content_sha256, str) or HASH64.fullmatch(content_sha256) is None:
            raise _prepare_error("LAYOUT_INVALID", f"{location}.records[{index}].content_sha256", "record content_sha256 must be a lowercase SHA-256")
        slug = value.get("slug")
        if slug is not None and (not isinstance(slug, str) or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) is None):
            raise _prepare_error("LAYOUT_INVALID", f"{location}.records[{index}].slug", "index slugs must be lowercase hyphenated values")
        path = value.get("path")
        if path is None and isinstance(slug, str):
            path = f"{public_id}-{slug}"
        normalized_path = _validate_index_path(collection, path, f"{location}.records[{index}].path")
        if normalized_path in seen_paths:
            raise _prepare_error("LAYOUT_INVALID", f"{location}.records[{index}].path", "index record paths must be unique")
        if not Path(normalized_path).name.startswith(public_id + "-") or len(Path(normalized_path).name) <= len(public_id) + 1:
            raise _prepare_error("LAYOUT_INVALID", f"{location}.records[{index}].path", "record directories must begin with their public ID")
        entry = dict(value)
        entry.update({"id": public_id, "source_key": source_key, "content_sha256": content_sha256, "path": normalized_path})
        normalized.append(entry)
        seen_ids.add(public_id)
        seen_sources.add(source_key)
        seen_paths.add(normalized_path)
    normalized.sort(key=lambda item: str(item["id"]))
    return {"version": INDEX_VERSION, "records": normalized, "retired_ids": sorted(retired_ids)}


def _target_layout_preflight(target: Path) -> tuple[Mapping[str, object] | None, dict[str, dict[str, object]], str, list[dict[str, str]]]:
    findings = _git_target_findings(target)
    try:
        before = _tree_fingerprint(target)
    except PreparationError as exc:
        findings.append(_projection_finding(exc.code, "target.tree", exc.remediation))
        before = sha256_hex([])
    layout: Mapping[str, object] | None = None
    indexes: dict[str, dict[str, object]] = {}
    try:
        document = _load_target_document(target, "public-project.yaml", "target.layout")
        errors = validate_layout(document, "target.layout")
        if errors or not isinstance(document, Mapping):
            raise _prepare_error("LAYOUT_INVALID", "target.layout", "repair public-project.yaml to public-project-layout/v1")
        _layout_collections(document)
        layout = document
    except PreparationError as exc:
        findings.append(_projection_finding(exc.code, "target.layout", exc.remediation))
    if layout is not None:
        plans, works = _layout_collections(layout)
        for collection, prefix, location in ((plans, "P", "target.plans"), (works, "W", "target.works")):
            try:
                _, collection_path = _target_locator(target, collection, location)
                if not collection_path.exists() or not collection_path.is_dir() or collection_path.is_symlink():
                    raise _prepare_error("LAYOUT_INVALID", location, "create the declared public collection directory")
                readme_relative = f"{collection}/README.md"
                readme, _ = _target_regular(_target_locator(target, readme_relative, location)[1], location)
                _marker_block(readme.decode("utf-8"), layout, location)
                indexes[collection] = _load_target_index(target, collection, prefix, location + ".index")
            except (PreparationError, UnicodeDecodeError) as exc:
                code = exc.code if isinstance(exc, PreparationError) else "LAYOUT_INVALID"
                remediation = exc.remediation if isinstance(exc, PreparationError) else "collection README must remain UTF-8"
                findings.append(_projection_finding(code, location, remediation))
    return layout, indexes, before, _dedupe_projection_findings(findings)


def _target_plan_directory(target: Path, collection: str, public_id: str, slug: str, location: str) -> tuple[str, Path]:
    relative = f"{collection}/{public_id}-{slug}"
    return _target_locator(target, relative, location)


def _catalog_line(entry: Mapping[str, object], collection: str, *, root: bool = False) -> str:
    public_id = str(entry["id"])
    title = str(entry.get("title", public_id)).replace("\r", " ").replace("\n", " ").replace("]", "\\]")
    path = Path(str(entry["path"]))
    link = path.as_posix() if root else path.name
    return f"- [{title}]({link}/README.md)"


def _catalog_text(index: Mapping[str, object], collection: str, *, root: bool = False) -> str:
    records = index.get("records", [])
    if not isinstance(records, list):
        return ""
    return "\n".join(_catalog_line(record, collection, root=root) for record in records if isinstance(record, Mapping))


def _metadata_bytes(record: Mapping[str, object], public_id: str) -> bytes:
    source = record.get("source")
    publication = record.get("publication")
    if not isinstance(source, Mapping) or not isinstance(publication, Mapping):
        raise _prepare_error("LAYOUT_INVALID", "record", "request records must include source and publication metadata")
    metadata = {
        "id": public_id,
        "title": str(record["title"]),
        "slug": str(record["slug"]),
        "status": "ready-for-publication",
        "visibility": "public",
        "rights_status": "cleared",
        "provenance": {
            "source_system": "agentic-art-orchestration",
            "source_ref": f"sha256:{source['canonical_sha256']}",
            "content_sha256": str(source["sha256"]),
        },
    }
    return _request_yaml_bytes(metadata)


def _generated_readme(record: Mapping[str, object], kind: str) -> bytes:
    body_name = "plan.md" if kind == "plan" else "record.md"
    return f"# {str(record['title']).replace(chr(10), ' ').replace(chr(13), ' ')}\n\n[{body_name}]({body_name})\n".encode("utf-8")


def _source_record_plan(
    record: Mapping[str, object],
    *,
    record_index: int,
    internal_root: Path,
    target: Path,
    layout: Mapping[str, object],
    collection: str,
) -> tuple[dict[str, object], list[dict[str, str]]]:
    findings: list[dict[str, str]] = []
    kind = record.get("record_kind")
    if kind not in {"plan", "work"}:
        return {}, [_projection_finding("LAYOUT_INVALID", f"records[{record_index}].record_kind", "use plan or work")]
    source_data = record.get("source")
    files = record.get("files")
    publication = record.get("publication")
    if not isinstance(source_data, Mapping) or not isinstance(files, list) or not isinstance(publication, Mapping):
        return {}, [_projection_finding("LAYOUT_INVALID", f"records[{record_index}]", "repair the closed request record")]
    for field in ("visibility", "rights_status", "consent_status"):
        if publication.get(field) != ("public" if field == "visibility" else "cleared"):
            findings.append(_projection_finding("UNKNOWN_CLEARANCE", f"records[{record_index}].publication.{field}", "obtain explicit human clearance before projection"))
    if not isinstance(record.get("slug"), str) or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(record.get("slug"))) is None:
        findings.append(_projection_finding("LAYOUT_INVALID", f"records[{record_index}].slug", "use a lowercase hyphenated public slug"))
    try:
        _, source_path = _internal_locator(internal_root, source_data.get("locator"), f"records[{record_index}].source.locator")
        _, source_hash = _read_regular(source_path, f"records[{record_index}].source.locator")
        if source_hash != source_data.get("canonical_sha256"):
            findings.append(_projection_finding("SOURCE_HASH_MISMATCH", f"records[{record_index}].source.locator", "refresh the request from the unchanged canonical artifact"))
    except PreparationError as exc:
        findings.append(_projection_finding(exc.code, f"records[{record_index}].source.locator", exc.remediation))

    body_role = "plan.md" if kind == "plan" else "record.md"
    prepared_files: list[dict[str, object]] = []
    file_bytes: dict[str, bytes] = {}
    media_policy = layout.get("media_policy")
    max_bytes = media_policy.get("max_file_bytes") if isinstance(media_policy, Mapping) else None
    allowed_extensions = set(media_policy.get("allowed_extensions", [])) if isinstance(media_policy, Mapping) and isinstance(media_policy.get("allowed_extensions"), list) else set()
    for file_index, file in enumerate(files):
        if not isinstance(file, Mapping):
            continue
        location = f"records[{record_index}].files[{file_index}]"
        role = file.get("role")
        try:
            source_locator, source_path = _internal_locator(internal_root, file.get("source_locator"), location + ".source_locator")
            content, actual_hash = _read_regular(source_path, location)
            if actual_hash != file.get("sha256"):
                findings.append(_projection_finding("SOURCE_HASH_MISMATCH", location + ".sha256", "refresh the candidate file hash before projection"))
            target_locator, target_path = _target_locator(target, file.get("target_locator"), location + ".target_locator")
            if role == "body" and target_locator != body_role:
                findings.append(_projection_finding("LAYOUT_INVALID", location + ".target_locator", f"use {body_role} for this record kind"))
            if role == "readme" and target_locator != "README.md":
                findings.append(_projection_finding("LAYOUT_INVALID", location + ".target_locator", "use README.md for a public record README"))
            if role == "process" and (kind != "work" or not target_locator.startswith("process/")):
                findings.append(_projection_finding("LAYOUT_INVALID", location + ".target_locator", "use process/<name> only for work records"))
            if role == "media":
                if not target_locator.startswith("media/"):
                    findings.append(_projection_finding("UNAPPROVED_MEDIA", location + ".target_locator", "put media below media/"))
                extension = Path(target_locator).suffix.lower()
                expected_mime = MIME_BY_EXTENSION.get(extension)
                if extension not in allowed_extensions or expected_mime is None or file.get("mime_type") != expected_mime:
                    findings.append(_projection_finding("UNAPPROVED_MEDIA", location, "use an allowed extension and matching declared MIME type"))
                if not isinstance(max_bytes, int) or len(content) > max_bytes:
                    findings.append(_projection_finding("UNAPPROVED_MEDIA", location, "keep media at or below the declared layout size limit"))
                if file.get("rights_status") != "cleared":
                    findings.append(_projection_finding("UNAPPROVED_MEDIA", location + ".rights_status", "obtain explicit media rights clearance"))
            elif file.get("rights_status") != "cleared":
                findings.append(_projection_finding("UNKNOWN_CLEARANCE", location + ".rights_status", "obtain explicit file rights clearance before projection"))
            if role in {"body", "readme", "process"}:
                try:
                    text_content = content.decode("utf-8")
                except UnicodeDecodeError:
                    findings.append(_projection_finding("FORBIDDEN_CONTENT", location, "public text files must be UTF-8"))
                else:
                    for security_finding in scan_public_projection(text_content, location):
                        findings.append(_projection_finding(str(security_finding.get("code")), str(security_finding.get("location", location)), str(security_finding.get("remediation", "remove unsafe public content"))))
            prepared_files.append({"role": str(role), "source_locator": source_locator, "target_locator": target_locator, "sha256": str(file.get("sha256")), "path": target_path})
            file_bytes[target_locator] = content
        except PreparationError as exc:
            findings.append(_projection_finding(exc.code, location, exc.remediation))
    source_hash = source_data.get("sha256")
    if isinstance(source_hash, str) and HASH64.fullmatch(source_hash) is not None:
        source_key = f"{kind}:{source_data.get('canonical_sha256')}"
    else:
        source_key = f"{kind}:{'0' * 64}"
    public_id: str | None = None
    slug = str(record.get("slug", "record"))
    result: dict[str, object] = {
        "record": record,
        "kind": str(kind),
        "collection": collection,
        "slug": slug,
        "source_key": source_key,
        "content_sha256": str(source_hash),
        "files": prepared_files,
        "file_bytes": file_bytes,
    }
    return result, _dedupe_projection_findings(findings)


def _allocate_public_ids(
    plans: list[dict[str, object]],
    indexes: Mapping[str, Mapping[str, object]],
    target: Path,
    collection_prefixes: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    findings: list[dict[str, str]] = []
    by_source: dict[str, dict[str, object]] = {}
    prefixes = dict(collection_prefixes or {})
    for plan in plans:
        collection = str(plan["collection"])
        prefixes.setdefault(collection, "P" if plan.get("kind") == "plan" else "W")
    for collection, index in indexes.items():
        prefixes.setdefault(collection, "P" if collection == "plans" else "W")
    maximum = {collection: 0 for collection in indexes}
    for collection, index in indexes.items():
        prefix = prefixes[collection]
        for retired in index.get("retired_ids", []):
            maximum[collection] = max(maximum[collection], int(str(retired)[1:]))
        for entry in index.get("records", []):
            if isinstance(entry, Mapping):
                public_id = str(entry["id"])
                maximum[collection] = max(maximum[collection], int(public_id[1:]))
                by_source[f"{collection}:{entry['source_key']}"] = dict(entry)
    new_by_kind: dict[str, int] = dict(maximum)
    for plan in sorted(plans, key=lambda item: (str(item["kind"]), str(item["source_key"]), str(item["slug"]))):
        collection = str(plan["collection"])
        existing = by_source.get(f"{collection}:{plan['source_key']}")
        if existing is not None:
            if existing.get("content_sha256") != plan.get("content_sha256"):
                findings.append(_projection_finding("TARGET_CONFLICT", f"{collection}.index.{plan['source_key']}", "the existing source key has different content; preserve it and use a new source or target decision"))
            public_id = str(existing["id"])
            plan["public_id"] = public_id
            plan["existing_entry"] = existing
            plan["path"] = str(existing["path"])
            continue
        new_by_kind[collection] += 1
        if new_by_kind[collection] > 9999:
            findings.append(_projection_finding("TARGET_CONFLICT", f"{collection}.index", "the four-digit public ID space is exhausted; choose a new target policy"))
            continue
        public_id = f"{prefixes[collection]}{new_by_kind[collection]:04d}"
        plan["public_id"] = public_id
        plan["existing_entry"] = None
        path, _ = _target_plan_directory(target, collection, public_id, str(plan["slug"]), f"{collection}.record")
        plan["path"] = path
    return plans, _dedupe_projection_findings(findings)


def _projection_index_entry(plan: Mapping[str, object]) -> dict[str, object]:
    record = plan["record"]
    return {
        "id": str(plan["public_id"]),
        "slug": str(plan["slug"]),
        "title": str(record["title"]),
        "path": str(plan["path"]),
        "source_key": str(plan["source_key"]),
        "content_sha256": str(plan["content_sha256"]),
        "status": "ready-for-publication",
        "visibility": "public",
        "rights_status": "cleared",
    }


def _index_bytes(index: Mapping[str, object]) -> bytes:
    records = sorted((dict(item) for item in index.get("records", []) if isinstance(item, Mapping)), key=lambda item: str(item.get("id", "")))
    value = {"version": INDEX_VERSION, "records": records, "retired_ids": sorted(str(item) for item in index.get("retired_ids", []))}
    return _request_yaml_bytes(value)


def _write_target_create_only(target: Path, relative: str, content: bytes) -> bool:
    _, path = _target_locator(target, relative, relative)
    if path.exists() or path.is_symlink():
        current, _ = _target_regular(path, relative)
        if current != content:
            raise _prepare_error("TARGET_CONFLICT", relative, "never overwrite existing target bytes")
        return False
    parent = path.parent
    current = target.expanduser().resolve(strict=False)
    for part in Path(relative).parent.parts:
        current = current / part
        try:
            if current.exists() and current.is_symlink():
                raise _prepare_error("SOURCE_PATH_UNSAFE", relative, "target parent paths may not contain symlinks")
            if current.exists() and not current.is_dir():
                raise _prepare_error("TARGET_CONFLICT", relative, "target parent is occupied by a file")
            current.mkdir(exist_ok=True)
        except OSError as exc:
            raise _prepare_error("FAILED", relative, "create the target staging parent manually and retry") from exc
    try:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        current, _ = _target_regular(path, relative)
        if current != content:
            raise _prepare_error("TARGET_CONFLICT", relative, "never overwrite a concurrently created target file")
        return False
    except OSError as exc:
        raise _prepare_error("FAILED", relative, "repair target write access and retry") from exc
    return True


def _append_target_file(target: Path, relative: str, expected: bytes, replacement: bytes) -> bool:
    _, path = _target_locator(target, relative, relative)
    current, _ = _target_regular(path, relative)
    if current != expected:
        raise _prepare_error("TARGET_CONFLICT", relative, "the target changed after planning; re-run the dry-run")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(replacement)
            handle.flush()
            os.fsync(handle.fileno())
        if _target_regular(path, relative)[0] != expected:
            raise _prepare_error("TARGET_CONFLICT", relative, "the target changed during the scaffold operation")
        os.replace(temporary, path)
        return True
    except PreparationError:
        raise
    except OSError as exc:
        raise _prepare_error("FAILED", relative, "append the target marker atomically after repairing access") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _replace_target_exact(target: Path, relative: str, expected: bytes, replacement: bytes) -> bool:
    """Atomically replace one allowlisted existing target file after recheck."""
    _, path = _target_locator(target, relative, relative)
    current, _ = _target_regular(path, relative)
    if current != expected:
        raise _prepare_error("TARGET_CONFLICT", relative, "the target changed after approval; preserve it and re-run the projection")
    if expected == replacement:
        return False
    temporary = path.with_name(f".{path.name}.{os.getpid()}.projection.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(replacement)
            handle.flush()
            os.fsync(handle.fileno())
        if _target_regular(path, relative)[0] != expected:
            raise _prepare_error("TARGET_CONFLICT", relative, "the target changed during the atomic projection")
        os.replace(temporary, path)
        return True
    except PreparationError:
        raise
    except OSError as exc:
        raise _prepare_error("FAILED", relative, "repair target write access and retry the projection") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _projection_parent_paths(target: Path, relative: str) -> list[Path]:
    current = target.expanduser().resolve(strict=False)
    paths: list[Path] = []
    for part in Path(relative).parent.parts:
        current = current / part
        paths.append(current)
    return paths


def _rollback_projection_transaction(
    target: Path,
    *,
    before: str,
    created_paths: list[str],
    replaced_originals: Mapping[str, tuple[bytes, bytes]],
    created_directories: set[Path],
    removed_originals: Mapping[str, bytes] | None = None,
) -> tuple[list[str], list[dict[str, str]], str]:
    """Restore only this transaction's exact paths and return residual evidence."""
    rollback_findings: list[dict[str, str]] = []
    for relative, original in (removed_originals or {}).items():
        try:
            if not _write_target_create_only(target, relative, original):
                current, _ = _target_regular(_target_locator(target, relative, relative)[1], relative)
                if current != original:
                    raise _prepare_error("TARGET_CONFLICT", relative, "removed asset was recreated concurrently")
        except (PreparationError, OSError):
            rollback_findings.append(_projection_finding("ROLLBACK_FAILED", relative, "preserve concurrent data and restore the removed asset manually"))
    for relative, (original, replacement) in reversed(list(replaced_originals.items())):
        try:
            current, _ = _target_regular(_target_locator(target, relative, relative)[1], relative)
            if current == original:
                continue
            if current != replacement:
                rollback_findings.append(_projection_finding("ROLLBACK_FAILED", relative, "the target changed concurrently; preserve the residual path for human recovery"))
                continue
            _replace_target_exact(target, relative, replacement, original)
        except (PreparationError, OSError):
            rollback_findings.append(_projection_finding("ROLLBACK_FAILED", relative, "restore the original target bytes manually; no reset was performed"))

    for relative in reversed(created_paths):
        try:
            _, path = _target_locator(target, relative, relative)
            if not path.exists():
                continue
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                rollback_findings.append(_projection_finding("ROLLBACK_FAILED", relative, "remove or preserve the unexpected residual path manually"))
                continue
            path.unlink()
        except (PreparationError, OSError):
            rollback_findings.append(_projection_finding("ROLLBACK_FAILED", relative, "remove the transaction-created residual path manually"))

    for directory in sorted(created_directories, key=lambda path: len(path.parts), reverse=True):
        try:
            if not directory.exists():
                continue
            if directory.is_symlink() or not directory.is_dir():
                rollback_findings.append(_projection_finding("ROLLBACK_FAILED", str(directory.relative_to(target)), "preserve the unexpected residual directory for human recovery"))
                continue
            directory.rmdir()
        except (OSError, ValueError):
            rollback_findings.append(_projection_finding("ROLLBACK_FAILED", str(directory.relative_to(target)), "remove only the empty transaction-created directory manually"))

    try:
        after = _tree_fingerprint(target)
    except PreparationError:
        after = sha256_hex([])
        rollback_findings.append(_projection_finding("ROLLBACK_FAILED", "target.tree", "restore and inspect the target fingerprint manually"))
    if after != before and not rollback_findings:
        rollback_findings.append(_projection_finding("ROLLBACK_FAILED", "target.tree", "restore the target fingerprint manually; no Git reset was performed"))
    residual: list[str] = []
    for finding in rollback_findings:
        location = finding.get("location", "")
        if location and location != "target.tree":
            residual.append(location)
    return sorted(set(residual)), _dedupe_projection_findings(rollback_findings), after


def _apply_projection_transaction(
    target: Path,
    *,
    before: str,
    planned_files: Mapping[str, bytes],
    target_updates: Mapping[str, tuple[bytes, bytes]],
    target_removals: Mapping[str, bytes] | None = None,
    fail_after: int | None = None,
) -> dict[str, object]:
    """Stage and apply only new record files plus index/catalog replacements."""
    target = target.expanduser().resolve(strict=False)
    changed_paths: list[str] = []
    created_paths: list[str] = []
    replaced_originals: dict[str, tuple[bytes, bytes]] = {}
    removed_originals: dict[str, bytes] = {}
    removals = target_removals or {}
    if set(removals) & (set(planned_files) | set(target_updates)):
        raise _prepare_error("LAYOUT_INVALID", "transaction", "removal and replacement paths overlap")
    parent_paths: set[Path] = set()
    for relative in planned_files:
        _target_locator(target, relative, relative)
        parent_paths.update(_projection_parent_paths(target, relative))
    for relative, values in target_updates.items():
        _target_locator(target, relative, relative)
        parent_paths.update(_projection_parent_paths(target, relative))
        if not isinstance(values, tuple) or len(values) != 2 or not all(isinstance(item, bytes) for item in values):
            raise _prepare_error("LAYOUT_INVALID", relative, "target updates must contain expected and replacement bytes")
    created_directories = {path for path in parent_paths if not path.exists()}

    try:
        if _tree_fingerprint(target) != before:
            raise _prepare_error("TARGET_CONFLICT", "target.tree", "the target changed after planning; re-run dry-run and approval")
        for relative in planned_files:
            _, path = _target_locator(target, relative, relative)
            if path.exists() or path.is_symlink():
                raise _prepare_error("TARGET_CONFLICT", relative, "the new record path appeared after planning; preserve it")
        for relative, (expected, _replacement) in target_updates.items():
            current, _ = _target_regular(_target_locator(target, relative, relative)[1], relative)
            if current != expected:
                raise _prepare_error("TARGET_CONFLICT", relative, "the target index or catalog changed after planning")
        for relative, expected in removals.items():
            if _target_regular(_target_locator(target, relative, relative)[1], relative)[0] != expected:
                raise _prepare_error("TARGET_CONFLICT", relative, "obsolete attested asset changed after planning")

        with tempfile.TemporaryDirectory(prefix="public-projection-stage-") as staging_name:
            staging = Path(staging_name)
            for relative, content in planned_files.items():
                staged = staging / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                with staged.open("xb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                if _sha256_bytes(staged.read_bytes()) != _sha256_bytes(content):
                    raise _prepare_error("FAILED", relative, "staged bytes did not verify; retry without applying partial output")

            if fail_after == 0:
                raise _prepare_error("FAILED", "transaction", "injected transaction failure before the first mutation")
            for relative, expected in sorted(removals.items()):
                path = _target_locator(target, relative, relative)[1]
                if _target_regular(path, relative)[0] != expected:
                    raise _prepare_error("TARGET_CONFLICT", relative, "obsolete attested asset changed during transaction")
                try:
                    path.unlink()
                except OSError as exc:
                    raise _prepare_error("FAILED", relative, "cannot remove obsolete attested asset") from exc
                removed_originals[relative] = expected
                changed_paths.append(relative)
                if fail_after is not None and len(changed_paths) >= fail_after:
                    raise _prepare_error("FAILED", relative, "injected failure after obsolete asset removal")
            for relative in sorted(planned_files):
                staged_bytes = (staging / relative).read_bytes()
                if not _write_target_create_only(target, relative, staged_bytes):
                    raise _prepare_error("TARGET_CONFLICT", relative, "a new record path was created concurrently")
                created_paths.append(relative)
                changed_paths.append(relative)
                if fail_after is not None and len(changed_paths) >= fail_after:
                    raise _prepare_error("FAILED", relative, "injected transaction failure after a partial write")

            for relative in sorted(target_updates):
                expected, replacement = target_updates[relative]
                if expected == replacement:
                    continue
                if _replace_target_exact(target, relative, expected, replacement):
                    replaced_originals[relative] = (expected, replacement)
                    changed_paths.append(relative)
                    if fail_after is not None and len(changed_paths) >= fail_after:
                        raise _prepare_error("FAILED", relative, "injected transaction failure after a catalog update")
        after = _tree_fingerprint(target)
        return {"outcome": "APPLIED", "changed_paths": sorted(changed_paths), "after": after, "findings": []}
    except PreparationError as exc:
        residual, rollback_findings, after = _rollback_projection_transaction(
            target,
            before=before,
            created_paths=created_paths,
            replaced_originals=replaced_originals,
            created_directories=created_directories,
            removed_originals=removed_originals,
        )
        findings: list[dict[str, str]] = []
        if exc.code in PUBLIC_PROJECTION_FINDING_CODES:
            findings.append(_projection_finding(exc.code, str(exc.location), exc.remediation))
        findings.extend(rollback_findings)
        if residual or rollback_findings:
            outcome = "FAILED"
        elif exc.code == "TARGET_CONFLICT":
            outcome = "BLOCKED_CONFLICT"
        else:
            outcome = "FAILED"
        return {
            "outcome": outcome,
            "changed_paths": residual,
            "after": after,
            "findings": _dedupe_projection_findings(findings),
            "remediations": sorted({str(item["remediation"]) for item in findings}),
        }


def _init_target_plan(target: Path) -> tuple[dict[str, bytes], list[dict[str, str]], str]:
    target = target.expanduser().resolve(strict=False)
    findings = _git_target_findings(target)
    try:
        before = _tree_fingerprint(target)
    except PreparationError as exc:
        findings.append(_projection_finding(exc.code, "target.tree", exc.remediation))
        before = sha256_hex([])
    planned: dict[str, bytes] = {}
    layout: Mapping[str, object] = DEFAULT_LAYOUT
    layout_path = target / "public-project.yaml"
    if layout_path.exists() or layout_path.is_symlink():
        try:
            document = _load_target_document(target, "public-project.yaml", "target.layout")
            errors = validate_layout(document, "target.layout")
            if errors or not isinstance(document, Mapping):
                raise _prepare_error("LAYOUT_INVALID", "target.layout", "repair public-project.yaml to public-project-layout/v1")
            _layout_collections(document)
            layout = document
        except PreparationError as exc:
            findings.append(_projection_finding(exc.code, "target.layout", exc.remediation))
    else:
        planned["public-project.yaml"] = _layout_bytes(DEFAULT_LAYOUT)
    try:
        plans, works = _layout_collections(layout)
    except PreparationError as exc:
        findings.append(_projection_finding(exc.code, exc.location, exc.remediation))
        return planned, _dedupe_projection_findings(findings), before
    if not (target / "README.md").exists() and not (target / "README.md").is_symlink():
        planned["README.md"] = b"# Public project\n"
    for collection, heading in ((plans, "# Plans\n\n"), (works, "# Works\n\n")):
        try:
            _, collection_path = _target_locator(target, collection, collection)
        except PreparationError as exc:
            findings.append(_projection_finding(exc.code, collection, exc.remediation))
            continue
        if collection_path.exists() and (collection_path.is_symlink() or not collection_path.is_dir()):
            findings.append(_projection_finding("LAYOUT_INVALID", collection, "the declared collection must be a directory"))
            continue
        readme_relative = f"{collection}/README.md"
        index_relative = f"{collection}/index.yaml"
        readme_path = _target_locator(target, readme_relative, f"target.{collection}.README")[1]
        if not readme_path.exists() and not readme_path.is_symlink():
            planned[readme_relative] = f"{heading}{layout['catalog_markers']['start']}\n{layout['catalog_markers']['end']}\n".encode("utf-8")
        elif readme_path.is_symlink():
            findings.append(_projection_finding("LAYOUT_INVALID", f"target.{collection}.README", "collection README may not be a symlink"))
        else:
            try:
                readme_bytes, _ = _target_regular(readme_path, f"target.{collection}.README")
                readme_text = readme_bytes.decode("utf-8")
                starts = readme_text.count(str(layout["catalog_markers"]["start"]))
                ends = readme_text.count(str(layout["catalog_markers"]["end"]))
                if starts > 1 or ends > 1 or (starts == 1 and ends == 1 and readme_text.find(str(layout["catalog_markers"]["start"])) >= readme_text.find(str(layout["catalog_markers"]["end"]))):
                    raise _prepare_error("LAYOUT_INVALID", f"target.{collection}.README", "collection README must contain at most one ordered marker pair")
                if starts == 0 and ends == 0:
                    planned[readme_relative] = _append_marker_block(readme_text, layout).encode("utf-8")
                elif starts != 1 or ends != 1:
                    raise _prepare_error("LAYOUT_INVALID", f"target.{collection}.README", "catalog markers must be supplied as one complete pair")
            except (PreparationError, UnicodeDecodeError) as exc:
                code = exc.code if isinstance(exc, PreparationError) else "LAYOUT_INVALID"
                remediation = exc.remediation if isinstance(exc, PreparationError) else "collection README must remain UTF-8"
                findings.append(_projection_finding(code, f"target.{collection}.README", remediation))
        index_path = _target_locator(target, index_relative, f"target.{collection}.index")[1]
        if not index_path.exists() and not index_path.is_symlink():
            planned[index_relative] = _index_scaffold_bytes()
        elif index_path.is_symlink():
            findings.append(_projection_finding("LAYOUT_INVALID", f"target.{collection}.index", "collection index may not be a symlink"))
        else:
            try:
                _load_target_index(target, collection, "P" if collection == plans else "W", f"target.{collection}.index")
            except PreparationError as exc:
                findings.append(_projection_finding(exc.code, f"target.{collection}.index", exc.remediation))
    return planned, _dedupe_projection_findings(findings), before


def init_target(target_root: Path, *, apply: bool) -> dict[str, object]:
    """Onboard only the empty/layout-compatible local target scaffold."""
    planned, findings, before = _init_target_plan(target_root)
    result: dict[str, object] = {
        "command": "init-target",
        "status": "BLOCKED_CONFLICT" if findings else ("DRY_RUN_READY" if not apply else "APPLIED"),
        "projection_id": None,
        "record_count": 0,
        "public_ids": [],
        "planned_paths": sorted(planned),
        "changed_paths": [],
        "finding_codes": sorted({finding["code"] for finding in findings}),
        "mutation_count": 0,
    }
    if findings or not apply:
        return result
    try:
        if _tree_fingerprint(target_root) != before:
            raise _prepare_error("TARGET_CONFLICT", "target.tree", "re-run init-target after the clean target fingerprint is stable")
        changed: list[str] = []
        for relative in sorted(planned):
            if (target_root / relative).exists() and (target_root / relative).is_file() and relative.endswith("README.md") and relative in planned and not (target_root / relative).is_symlink():
                # Existing README entries are marker appends; newly planned README
                # files are handled by the create-only path below.
                existing = (target_root / relative).read_bytes()
                if existing != planned[relative]:
                    if _append_target_file(target_root, relative, existing, planned[relative]):
                        changed.append(relative)
                continue
            if _write_target_create_only(target_root, relative, planned[relative]):
                changed.append(relative)
        result["changed_paths"] = changed
        result["mutation_count"] = len(changed)
        return result
    except PreparationError as exc:
        result["status"] = "BLOCKED_CONFLICT" if exc.code in {"TARGET_CONFLICT", "SOURCE_PATH_UNSAFE", "LAYOUT_INVALID"} else "FAILED"
        result["finding_codes"] = [exc.code]
        result["changed_paths"] = []
        result["mutation_count"] = 0
        return result


def _result_bytes(result: Mapping[str, object]) -> bytes:
    return json.dumps(dict(result), ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _write_projection_result(
    state_root: Path,
    projection_id: str,
    result: Mapping[str, object],
    *,
    allow_transition: bool = False,
) -> None:
    errors = validate_result(result)
    if errors:
        raise _prepare_error("LAYOUT_INVALID", "result", "repair the generated public-projection-result/v1 evidence")
    state_root = state_root.expanduser().resolve(strict=False)
    run_directory = state_root / projection_id
    if run_directory.exists() and run_directory.is_symlink():
        raise _prepare_error("SOURCE_PATH_UNSAFE", "result", "run evidence directories may not be symlinks")
    try:
        run_directory.mkdir(parents=True, exist_ok=True)
        if run_directory.resolve(strict=False) != run_directory:
            raise _prepare_error("SOURCE_PATH_UNSAFE", "result", "run evidence must remain below state_root")
    except PreparationError:
        raise
    except OSError as exc:
        raise _prepare_error("FAILED", "result", "create the external run evidence directory and retry") from exc
    target = resolve_run_destination(state_root, projection_id) / "public-projection-result.json"
    rendered = _result_bytes(result)
    if target.is_symlink():
        raise _prepare_error("SOURCE_PATH_UNSAFE", "result", "result evidence may not be a symlink")
    if target.exists():
        try:
            current = target.read_bytes()
        except OSError as exc:
            raise _prepare_error("TARGET_CONFLICT", "result", "inspect the existing run evidence without overwriting it") from exc
        if current == rendered:
            return
        if not allow_transition:
            raise _prepare_error("TARGET_CONFLICT", "result", "use a new projection ID; result evidence is create-only")
        try:
            previous = json.loads(current.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _prepare_error("TARGET_CONFLICT", "result", "preserve malformed result evidence and use a new projection ID") from exc
        if not isinstance(previous, Mapping) or previous.get("projection_id") != projection_id or previous.get("request_sha256") != result.get("request_sha256"):
            raise _prepare_error("TARGET_CONFLICT", "result", "do not replace evidence for a different projection request")
        try:
            metadata = target.lstat()
        except OSError as exc:
            raise _prepare_error("TARGET_CONFLICT", "result", "inspect the existing result evidence without overwriting it") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise _prepare_error("SOURCE_PATH_UNSAFE", "result", "result evidence must be a regular, non-aliased file")
        temporary = target.with_name(f".{target.name}.{os.getpid()}.transition.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            if target.read_bytes() != current:
                raise _prepare_error("TARGET_CONFLICT", "result", "result evidence changed during the atomic transition")
            os.replace(temporary, target)
            return
        except PreparationError:
            raise
        except OSError as exc:
            raise _prepare_error("FAILED", "result", "write the atomic result transition after repairing the state root") from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() != rendered:
                raise _prepare_error("TARGET_CONFLICT", "result", "do not replace concurrently-created result evidence")
    except PreparationError:
        raise
    except OSError as exc:
        raise _prepare_error("FAILED", "result", "repair the external state root and retry create-only evidence write") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _sanitized_request_findings(request: Mapping[str, object]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for finding in request_policy_findings(request):
        findings.append(_projection_finding(
            str(finding.get("code", "FORBIDDEN_CONTENT")),
            str(finding.get("location", "request")),
            str(finding.get("remediation", "repair the public projection request")),
        ))
    return _dedupe_projection_findings(findings)


def _plan_target_files(plan: Mapping[str, object], layout: Mapping[str, object]) -> dict[str, bytes]:
    record = plan["record"]
    directory = str(plan["path"])
    files: dict[str, bytes] = {}
    file_bytes = plan.get("file_bytes", {})
    if isinstance(file_bytes, Mapping):
        for target_locator, content in file_bytes.items():
            if isinstance(target_locator, str) and isinstance(content, bytes):
                files[f"{directory}/{target_locator}"] = content
    if not any(str(item.get("role")) == "readme" for item in plan.get("files", []) if isinstance(item, Mapping)):
        files[f"{directory}/README.md"] = _generated_readme(record, str(plan["kind"]))
    files[f"{directory}/metadata.yaml"] = _metadata_bytes(record, str(plan["public_id"]))
    return files


def _existing_record_matches(target: Path, plan: Mapping[str, object], expected_files: Mapping[str, bytes]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    directory = str(plan["path"])
    try:
        _, directory_path = _target_locator(target, directory, f"{plan['collection']}.record")
        if not directory_path.exists() or directory_path.is_symlink() or not directory_path.is_dir():
            raise _prepare_error("TARGET_CONFLICT", directory, "the indexed public record directory is missing or incompatible")
        for relative, expected in sorted(expected_files.items()):
            _, path = _target_locator(target, relative, relative)
            if not path.exists() or path.is_symlink():
                raise _prepare_error("TARGET_CONFLICT", relative, "the indexed public record is missing a managed file")
            actual, _ = _target_regular(path, relative)
            if actual != expected:
                raise _prepare_error("TARGET_CONFLICT", relative, "the indexed public record bytes differ; preserve existing content")
    except PreparationError as exc:
        findings.append(_projection_finding(exc.code, str(exc.location), exc.remediation))
    return findings


PROJECTION_POLICY_CODES = {
    "UNKNOWN_CLEARANCE", "UNAPPROVED_MEDIA", "SOURCE_PATH_UNSAFE", "SOURCE_HASH_MISMATCH",
    "FORBIDDEN_CONTENT", "CREDENTIAL", "PRIVATE_URL", "ABSOLUTE_PATH", "FORBIDDEN_ARTIFACT",
    "INTERNAL_REFERENCE", "REMOTE_OPERATION",
}


def _projection_plan_data(
    request: Mapping[str, object],
    *,
    internal_output_root: Path,
    public_projection_root: Path,
) -> dict[str, object]:
    """Build the same closed plan inputs used by dry-run and apply.

    The returned mapping contains source bytes only in process memory.  It is
    deliberately not suitable for result evidence; callers must project only
    the generated public paths and metadata.
    """
    projection_id = request.get("projection_id")
    if not isinstance(projection_id, str) or STABLE_ID.fullmatch(projection_id) is None:
        raise _prepare_error("PROJECTION_ID_INVALID", "request.projection_id", "use the stable projection identifier from the request")
    structural = validate_request(request, "request")
    if structural:
        raise _prepare_error("LAYOUT_INVALID", "request", "repair the public-projection-request/v1 contract before planning")

    layout, indexes, before, findings = _target_layout_preflight(public_projection_root)
    findings.extend(_sanitized_request_findings(request))
    source_refs = [
        {"record_kind": str(record["record_kind"]), "source_sha256": str(record["source"]["sha256"])}
        for record in request.get("records", [])
        if isinstance(record, Mapping) and isinstance(record.get("source"), Mapping)
    ]
    source_refs = sorted(source_refs, key=lambda item: (item["record_kind"], item["source_sha256"]))

    plans: list[dict[str, object]] = []
    collection_map: dict[str, str] = {}
    if layout is not None:
        plans_collection, works_collection = _layout_collections(layout)
        collection_map = {"plan": plans_collection, "work": works_collection}
        for record_index, record in enumerate(request.get("records", [])):
            if not isinstance(record, Mapping):
                continue
            collection = collection_map.get(str(record.get("record_kind")))
            if collection is None:
                findings.append(_projection_finding("LAYOUT_INVALID", f"records[{record_index}].record_kind", "use plan or work"))
                continue
            plan, record_findings = _source_record_plan(
                record,
                record_index=record_index,
                internal_root=internal_output_root,
                target=public_projection_root,
                layout=layout,
                collection=collection,
            )
            findings.extend(record_findings)
            if plan:
                plans.append(plan)

    public_ids: list[str] = []
    planned_paths: set[str] = set()
    target_updates: dict[str, tuple[bytes, bytes]] = {}
    root_catalog_enabled = False
    has_policy = any(finding.get("code") in PROJECTION_POLICY_CODES for finding in findings)
    allocation_findings: list[dict[str, str]] = []
    candidate_indexes: dict[str, dict[str, object]] = {}
    if layout is not None and indexes and not has_policy:
        plans, allocation_findings = _allocate_public_ids(
            plans,
            indexes,
            public_projection_root,
            {collection_map["plan"]: "P", collection_map["work"]: "W"},
        )
        findings.extend(allocation_findings)
        if not allocation_findings:
            candidate_indexes = {
                collection: {
                    "version": INDEX_VERSION,
                    "records": [dict(item) for item in index.get("records", []) if isinstance(item, Mapping)],
                    "retired_ids": list(index.get("retired_ids", [])),
                }
                for collection, index in indexes.items()
            }
            for plan in plans:
                public_ids.append(str(plan["public_id"]))
                expected_files = _plan_target_files(plan, layout)
                plan["expected_files"] = expected_files
                plan["is_new"] = plan.get("existing_entry") is None
                if plan["is_new"]:
                    directory = str(plan["path"])
                    _, directory_path = _target_locator(public_projection_root, directory, f"{plan['collection']}.record")
                    if directory_path.exists() or directory_path.is_symlink():
                        findings.append(_projection_finding("TARGET_CONFLICT", directory, "the proposed public record directory already exists"))
                    else:
                        planned_paths.update(expected_files)
                    candidate_indexes[str(plan["collection"])]["records"].append(_projection_index_entry(plan))
                else:
                    findings.extend(_existing_record_matches(public_projection_root, plan, expected_files))

            for collection, candidate_index in candidate_indexes.items():
                has_new = any(plan.get("is_new") and plan.get("collection") == collection for plan in plans)
                if not has_new:
                    continue
                index_relative = f"{collection}/index.yaml"
                index_path = _target_locator(public_projection_root, index_relative, index_relative)[1]
                current_index, _ = _target_regular(index_path, index_relative)
                replacement_index = _index_bytes(candidate_index)
                if current_index != replacement_index:
                    target_updates[index_relative] = (current_index, replacement_index)
                    planned_paths.add(index_relative)
                readme_relative = f"{collection}/README.md"
                readme_path = _target_locator(public_projection_root, readme_relative, readme_relative)[1]
                try:
                    current_readme, _ = _target_regular(readme_path, readme_relative)
                    current_text = current_readme.decode("utf-8")
                    desired_text = _replace_marker_block(
                        current_text,
                        layout,
                        _catalog_text(candidate_index, collection),
                        readme_relative,
                    )
                except (PreparationError, UnicodeDecodeError) as exc:
                    code = exc.code if isinstance(exc, PreparationError) else "LAYOUT_INVALID"
                    remediation = exc.remediation if isinstance(exc, PreparationError) else "collection README must remain UTF-8"
                    findings.append(_projection_finding(code, readme_relative, remediation))
                else:
                    desired_readme = desired_text.encode("utf-8")
                    if current_readme != desired_readme:
                        target_updates[readme_relative] = (current_readme, desired_readme)
                        planned_paths.add(readme_relative)

            plan_collection = collection_map.get("plan")
            plan_index = candidate_indexes.get(plan_collection) if plan_collection else None
            has_new_plan = any(
                plan.get("is_new") and plan.get("collection") == plan_collection
                for plan in plans
                if isinstance(plan, Mapping)
            )
            if has_new_plan and isinstance(plan_index, Mapping):
                try:
                    root_update = _root_catalog_update(public_projection_root, layout, plan_index)
                except (PreparationError, UnicodeDecodeError) as exc:
                    code = exc.code if isinstance(exc, PreparationError) else "LAYOUT_INVALID"
                    remediation = exc.remediation if isinstance(exc, PreparationError) else "root README must remain UTF-8"
                    findings.append(_projection_finding(code, "target.root.README", remediation))
                else:
                    root_catalog_enabled = root_update is not None
                    if root_update is not None:
                        current_root, desired_root = root_update
                        if current_root != desired_root:
                            target_updates["README.md"] = (current_root, desired_root)
                            planned_paths.add("README.md")

    return {
        "projection_id": projection_id,
        "request_sha256": request_sha256(request),
        "source_refs": source_refs,
        "layout": layout,
        "indexes": indexes,
        "before": before,
        "findings": _dedupe_projection_findings(findings),
        "plans": plans,
        "public_ids": sorted(set(public_ids)),
        "planned_paths": sorted(planned_paths),
        "target_updates": target_updates,
        "candidate_indexes": candidate_indexes,
        "root_catalog_enabled": root_catalog_enabled,
    }


def _project_dry_run_result(
    request: Mapping[str, object],
    *,
    request_path: Path,
    internal_output_root: Path,
    public_projection_root: Path,
) -> dict[str, object]:
    projection_id = request.get("projection_id")
    if not isinstance(projection_id, str) or STABLE_ID.fullmatch(projection_id) is None:
        raise _prepare_error("PROJECTION_ID_INVALID", "request.projection_id", "use the stable projection identifier from the request")
    structural = validate_request(request, "request")
    if structural:
        raise _prepare_error("LAYOUT_INVALID", "request", "repair the public-projection-request/v1 contract before planning")
    request_hash = request_sha256(request)
    layout, indexes, before, findings = _target_layout_preflight(public_projection_root)
    findings.extend(_sanitized_request_findings(request))
    source_refs = [
        {"record_kind": str(record["record_kind"]), "source_sha256": str(record["source"]["sha256"])}
        for record in request.get("records", [])
        if isinstance(record, Mapping) and isinstance(record.get("source"), Mapping)
    ]
    source_refs = sorted(source_refs, key=lambda item: (item["record_kind"], item["source_sha256"]))
    plans: list[dict[str, object]] = []
    if layout is not None:
        collection_map = {"plan": _layout_collections(layout)[0], "work": _layout_collections(layout)[1]}
        for record_index, record in enumerate(request.get("records", [])):
            if not isinstance(record, Mapping):
                continue
            collection = collection_map.get(str(record.get("record_kind")))
            if collection is None:
                findings.append(_projection_finding("LAYOUT_INVALID", f"records[{record_index}].record_kind", "use plan or work"))
                continue
            plan, record_findings = _source_record_plan(
                record,
                record_index=record_index,
                internal_root=internal_output_root,
                target=public_projection_root,
                layout=layout,
                collection=collection,
            )
            findings.extend(record_findings)
            if plan:
                plans.append(plan)
    policy_codes = {
        "UNKNOWN_CLEARANCE", "UNAPPROVED_MEDIA", "SOURCE_PATH_UNSAFE", "SOURCE_HASH_MISMATCH",
        "FORBIDDEN_CONTENT", "CREDENTIAL", "PRIVATE_URL", "ABSOLUTE_PATH", "FORBIDDEN_ARTIFACT",
        "INTERNAL_REFERENCE", "REMOTE_OPERATION",
    }
    has_policy = any(finding.get("code") in policy_codes for finding in findings)
    public_ids: list[str] = []
    planned_paths: set[str] = set()
    if layout is not None and indexes and not has_policy:
        plans, allocation_findings = _allocate_public_ids(
            plans,
            indexes,
            public_projection_root,
            {collection_map["plan"]: "P", collection_map["work"]: "W"},
        )
        findings.extend(allocation_findings)
        if not allocation_findings:
            for plan in plans:
                public_ids.append(str(plan["public_id"]))
                expected_files = _plan_target_files(plan, layout)
                if plan.get("existing_entry") is not None:
                    findings.extend(_existing_record_matches(public_projection_root, plan, expected_files))
                else:
                    directory = str(plan["path"])
                    _, directory_path = _target_locator(public_projection_root, directory, f"{plan['collection']}.record")
                    if directory_path.exists() or directory_path.is_symlink():
                        findings.append(_projection_finding("TARGET_CONFLICT", directory, "the proposed public record directory already exists"))
                    else:
                        planned_paths.update(expected_files)
                collection = str(plan["collection"])
                if plan.get("existing_entry") is None:
                    planned_paths.add(f"{collection}/index.yaml")
            candidate_indexes: dict[str, dict[str, object]] = {collection: {"version": INDEX_VERSION, "records": [dict(item) for item in index.get("records", []) if isinstance(item, Mapping)], "retired_ids": list(index.get("retired_ids", []))} for collection, index in indexes.items()}
            for plan in plans:
                if plan.get("existing_entry") is None:
                    candidate_indexes[str(plan["collection"])]["records"].append(_projection_index_entry(plan))
            for collection, candidate_index in candidate_indexes.items():
                current_index = indexes[collection]
                if any(plan.get("existing_entry") is None and plan.get("collection") == collection for plan in plans):
                    planned_paths.add(f"{collection}/index.yaml")
                    readme_relative = f"{collection}/README.md"
                    try:
                        readme_bytes, _ = _target_regular(_target_locator(public_projection_root, readme_relative, readme_relative)[1], readme_relative)
                        current_text = readme_bytes.decode("utf-8")
                        desired_text = _replace_marker_block(current_text, layout, _catalog_text(candidate_index, collection), readme_relative)
                        if desired_text != current_text:
                            planned_paths.add(readme_relative)
                    except (PreparationError, UnicodeDecodeError) as exc:
                        code = exc.code if isinstance(exc, PreparationError) else "LAYOUT_INVALID"
                        remediation = exc.remediation if isinstance(exc, PreparationError) else "collection README must remain UTF-8"
                        findings.append(_projection_finding(code, readme_relative, remediation))
            plan_collection = collection_map.get("plan")
            plan_index = candidate_indexes.get(plan_collection) if plan_collection else None
            has_new_plan = any(
                plan.get("existing_entry") is None and plan.get("collection") == plan_collection
                for plan in plans
                if isinstance(plan, Mapping)
            )
            if has_new_plan and isinstance(plan_index, Mapping):
                try:
                    root_update = _root_catalog_update(public_projection_root, layout, plan_index)
                except (PreparationError, UnicodeDecodeError) as exc:
                    code = exc.code if isinstance(exc, PreparationError) else "LAYOUT_INVALID"
                    remediation = exc.remediation if isinstance(exc, PreparationError) else "root README must remain UTF-8"
                    findings.append(_projection_finding(code, "target.root.README", remediation))
                else:
                    if root_update is not None and root_update[0] != root_update[1]:
                        planned_paths.add("README.md")
    findings = _dedupe_projection_findings(findings)
    if any(finding.get("code") in policy_codes for finding in findings):
        status = "BLOCKED_POLICY"
        public_ids = []
        planned_paths = set()
    elif any(finding.get("code") in {"TARGET_CONFLICT", "TARGET_DIRTY", "LAYOUT_INVALID"} for finding in findings):
        status = "BLOCKED_CONFLICT"
        planned_paths = set()
    else:
        status = "DRY_RUN_READY"
    remediations = sorted({str(finding["remediation"]) for finding in findings})
    result: dict[str, object] = {
        "contract_version": "public-projection-result/v1",
        "projection_id": projection_id,
        "generated_at": str(request["generated_at"]),
        "status": status,
        "projection_mode": HUMAN_APPROVED_MODE,
        "request_sha256": request_hash,
        "approval_sha256": None,
        "source_refs": source_refs,
        "public_ids": sorted(set(public_ids)),
        "changed_paths": [],
        "planned_paths": sorted(planned_paths),
        "target": {
            "root_role": "public_projection_root",
            "mutation_count": 0,
            "before_fingerprint": before,
            "after_fingerprint": before,
        },
        "findings": findings,
        "remediations": remediations,
        "human_gate": {"status": "BLOCKED_HUMAN", "operation": "public_share"},
        "remote_operations": [],
        "child_mutations": [],
        "privacy": {
            "internal_content_stored": False,
            "credential_stored": False,
            "raw_conversation_stored": False,
            "media_bytes_stored": False,
            "direct_identifier_stored": False,
        },
    }
    result_errors = validate_result(result)
    if result_errors:
        raise _prepare_error("LAYOUT_INVALID", "result", "repair the generated metadata-only result evidence")
    return result


def project_dry_run(
    request_path: Path,
    *,
    internal_output_root: Path,
    public_projection_root: Path,
    state_root: Path,
) -> dict[str, object]:
    """Plan a public projection and write only create-only result evidence."""
    locator, resolved_request = _source_locator(internal_output_root, request_path, "request")
    request = _load_document(resolved_request)
    if not isinstance(request, Mapping):
        raise _prepare_error("LAYOUT_INVALID", "request", "provide a public-projection-request/v1 mapping")
    result = _project_dry_run_result(
        request,
        request_path=resolved_request,
        internal_output_root=internal_output_root.expanduser().resolve(strict=False),
        public_projection_root=public_projection_root.expanduser().resolve(strict=False),
    )
    _write_projection_result(state_root.expanduser().resolve(strict=False), str(request["projection_id"]), result)
    return result


def _load_approval_document(path: Path) -> object:
    """Read a separately supplied approval without accepting path aliases."""
    candidate = path.expanduser()
    if not candidate.is_absolute():
        if ".." in candidate.parts:
            raise _prepare_error("SOURCE_PATH_UNSAFE", "approval", "use a separate approval file without traversal")
        candidate = Path.cwd() / candidate
    if ".." in candidate.parts:
        raise _prepare_error("SOURCE_PATH_UNSAFE", "approval", "use a separate approval file without traversal")
    try:
        if candidate.is_symlink():
            raise _prepare_error("SOURCE_PATH_UNSAFE", "approval", "the approval file may not be a symlink")
        # The macOS temporary root commonly contains the harmless /var ->
        # /private/var alias.  Resolve parent aliases, but still reject a
        # symlink at the approval file itself.
        candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _prepare_error("MISSING_APPROVAL", "approval", "provide a readable separate approval file") from exc
    _read_regular(candidate, "approval")
    return _load_document(candidate)


def _projection_result(
    request: Mapping[str, object],
    plan_data: Mapping[str, object],
    *,
    status: str,
    approval_digest: str | None,
    findings: list[Mapping[str, object]],
    public_ids: list[str] | None = None,
    planned_paths: list[str] | None = None,
    changed_paths: list[str] | None = None,
    before: str | None = None,
    after: str | None = None,
    human_gate: str = "BLOCKED_HUMAN",
    extra_remediations: list[str] | None = None,
    projection_mode: str = HUMAN_APPROVED_MODE,
) -> dict[str, object]:
    safe_findings = _dedupe_projection_findings(list(findings))
    changed = sorted(set(changed_paths or []))
    result: dict[str, object] = {
        "contract_version": "public-projection-result/v1",
        "projection_id": str(plan_data["projection_id"]),
        "generated_at": str(request["generated_at"]),
        "status": status,
        "projection_mode": projection_mode,
        "request_sha256": str(plan_data["request_sha256"]),
        "approval_sha256": approval_digest,
        "source_refs": list(plan_data.get("source_refs", [])),
        "public_ids": sorted(set(public_ids if public_ids is not None else plan_data.get("public_ids", []))),
        "changed_paths": changed,
        "planned_paths": sorted(set(planned_paths if planned_paths is not None else plan_data.get("planned_paths", []))),
        "target": {
            "root_role": "public_projection_root",
            "mutation_count": len(changed),
            "before_fingerprint": before or str(plan_data["before"]),
            "after_fingerprint": after or before or str(plan_data["before"]),
        },
        "findings": safe_findings,
        "remediations": sorted({
            *(str(item["remediation"]) for item in safe_findings),
            *(extra_remediations or []),
        }),
        "human_gate": {"status": human_gate, "operation": "public_share"},
        "remote_operations": [],
        "child_mutations": [],
        "privacy": {
            "internal_content_stored": False,
            "credential_stored": False,
            "raw_conversation_stored": False,
            "media_bytes_stored": False,
            "direct_identifier_stored": False,
        },
    }
    errors = validate_result(result)
    if errors:
        raise _prepare_error("LAYOUT_INVALID", "result", "repair the generated public-projection result before writing evidence")
    return result


def _replay_dirty_target_allowed(target: Path, plan_data: Mapping[str, object]) -> bool:
    """Allow only the exact uncommitted paths created by an earlier apply."""
    if not any(finding.get("code") == "TARGET_DIRTY" for finding in plan_data.get("findings", [])):
        return False
    if any(
        finding.get("code") in PROJECTION_POLICY_CODES | {"TARGET_CONFLICT", "LAYOUT_INVALID"}
        for finding in plan_data.get("findings", [])
    ):
        return False
    plans = plan_data.get("plans", [])
    if not isinstance(plans, list) or not plans or any(plan.get("is_new") for plan in plans if isinstance(plan, Mapping)):
        return False
    observed = _git_target_status_paths(target)
    if not observed:
        return False
    managed: set[str] = set()
    for plan in plans:
        if not isinstance(plan, Mapping):
            return False
        managed.update(str(path) for path in plan.get("expected_files", {}) if isinstance(path, str))
        collection = str(plan.get("collection", ""))
        if collection:
            managed.add(f"{collection}/index.yaml")
            managed.add(f"{collection}/README.md")
    if plan_data.get("root_catalog_enabled") is True:
        managed.add("README.md")
    return set(observed).issubset(managed)


def _existing_result_request_conflict(state_root: Path, projection_id: str, request_hash: str) -> bool:
    """Detect an occupied evidence slot for another canonical request."""
    evidence = resolve_run_destination(state_root, projection_id) / "public-projection-result.json"
    if not evidence.exists():
        return False
    if evidence.is_symlink():
        raise _prepare_error("SOURCE_PATH_UNSAFE", "result", "result evidence may not be a symlink")
    try:
        current = json.loads(evidence.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _prepare_error("TARGET_CONFLICT", "result", "inspect the existing result evidence before applying") from exc
    return not isinstance(current, Mapping) or current.get("request_sha256") != request_hash


def project_apply(
    request_path: Path,
    *,
    approval_path: Path | None,
    internal_output_root: Path,
    public_projection_root: Path,
    state_root: Path,
    now: datetime | None = None,
    fail_after: int | None = None,
) -> dict[str, object]:
    """Apply a human-approved local projection with exact-path rollback."""
    _locator, resolved_request = _source_locator(internal_output_root, request_path, "request")
    request = _load_document(resolved_request)
    if not isinstance(request, Mapping):
        raise _prepare_error("LAYOUT_INVALID", "request", "provide a public-projection-request/v1 mapping")
    plan_data = _projection_plan_data(
        request,
        internal_output_root=internal_output_root.expanduser().resolve(strict=False),
        public_projection_root=public_projection_root.expanduser().resolve(strict=False),
    )
    state_root = state_root.expanduser().resolve(strict=False)
    if _existing_result_request_conflict(state_root, str(plan_data["projection_id"]), str(plan_data["request_sha256"])):
        findings = list(plan_data["findings"]) + [_projection_finding("TARGET_CONFLICT", "result", "use a new projection ID for a different canonical request")]
        result = _projection_result(
            request,
            plan_data,
            status="BLOCKED_CONFLICT",
            approval_digest=None,
            findings=findings,
            public_ids=[],
            planned_paths=[],
        )
        _write_projection_result(state_root, str(plan_data["projection_id"]), result, allow_transition=True)
        return result

    approval: object = None
    if approval_path is not None:
        try:
            approval = _load_approval_document(approval_path)
        except (PreparationError, PublicProjectionError, OSError, UnicodeError, TypeError, ValueError):
            approval = None
    approval_findings, approval_digest = _approval_findings(approval, request, now=now)
    findings = list(plan_data["findings"]) + approval_findings
    if _replay_dirty_target_allowed(public_projection_root, plan_data):
        findings = [finding for finding in findings if finding.get("code") != "TARGET_DIRTY"]
    findings = _dedupe_projection_findings(findings)

    if any(finding.get("code") in PROJECTION_POLICY_CODES for finding in findings):
        result = _projection_result(request, plan_data, status="BLOCKED_POLICY", approval_digest=approval_digest, findings=findings, public_ids=[], planned_paths=[])
        _write_projection_result(state_root, str(plan_data["projection_id"]), result, allow_transition=True)
        return result
    if any(finding.get("code") in {"TARGET_CONFLICT", "TARGET_DIRTY", "LAYOUT_INVALID"} for finding in findings):
        result = _projection_result(request, plan_data, status="BLOCKED_CONFLICT", approval_digest=approval_digest, findings=findings, public_ids=[], planned_paths=[])
        _write_projection_result(state_root, str(plan_data["projection_id"]), result, allow_transition=True)
        return result
    if approval_findings:
        result = _projection_result(request, plan_data, status="BLOCKED_HUMAN", approval_digest=None, findings=findings, human_gate="BLOCKED_HUMAN")
        _write_projection_result(state_root, str(plan_data["projection_id"]), result, allow_transition=True)
        return result

    plans = [plan for plan in plan_data.get("plans", []) if isinstance(plan, Mapping)]
    if not plans or not all(isinstance(plan.get("expected_files"), Mapping) for plan in plans):
        result = _projection_result(
            request,
            plan_data,
            status="BLOCKED_CONFLICT",
            approval_digest=approval_digest,
            findings=[*findings, _projection_finding("LAYOUT_INVALID", "projection.plan", "produce a complete target plan before applying")],
            public_ids=[],
            planned_paths=[],
            human_gate="APPROVED",
        )
        _write_projection_result(state_root, str(plan_data["projection_id"]), result, allow_transition=True)
        return result

    planned_files: dict[str, bytes] = {}
    for plan in plans:
        if plan.get("is_new"):
            expected_files = plan.get("expected_files")
            if isinstance(expected_files, Mapping):
                planned_files.update({str(path): content for path, content in expected_files.items() if isinstance(path, str) and isinstance(content, bytes)})
    target_updates = plan_data.get("target_updates", {}) if isinstance(plan_data.get("target_updates"), Mapping) else {}
    if not planned_files and not target_updates:
        transaction = {"outcome": "ALREADY_PROJECTED", "changed_paths": [], "after": str(plan_data["before"]), "findings": []}
    else:
        transaction = _apply_projection_transaction(
            public_projection_root,
            before=str(plan_data["before"]),
            planned_files=planned_files,
            target_updates=target_updates,
            fail_after=fail_after,
        )
    status = str(transaction["outcome"])
    transaction_findings = list(transaction.get("findings", []))
    result = _projection_result(
        request,
        plan_data,
        status=status,
        approval_digest=approval_digest,
        findings=[*findings, *transaction_findings],
        public_ids=plan_data.get("public_ids", []) if status in {"APPLIED", "ALREADY_PROJECTED", "FAILED"} else [],
        planned_paths=plan_data.get("planned_paths", []) if status in {"APPLIED", "FAILED"} else [],
        changed_paths=transaction.get("changed_paths", []) if isinstance(transaction.get("changed_paths"), list) else [],
        before=str(plan_data["before"]),
        after=str(transaction.get("after", plan_data["before"])),
        human_gate="APPROVED",
        extra_remediations=list(transaction.get("remediations", [])) if isinstance(transaction.get("remediations"), list) else [],
    )
    _write_projection_result(state_root, str(plan_data["projection_id"]), result, allow_transition=True)
    return result


def _optional_resolution_role(resolution: Mapping[str, object], role: str) -> Path | None:
    """Resolve an optional destination without accepting a caller-supplied path."""
    destinations = resolution.get("destinations")
    item = destinations.get(role) if isinstance(destinations, Mapping) else None
    path = item.get("path") if isinstance(item, Mapping) else None
    if path is None:
        return None
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise _prepare_error("AUTHORITY_INVALID", f"destination_resolution.destinations.{role}", "use the absolute role resolved by the selected destination profile")
    return Path(path).expanduser().resolve(strict=False)


def _request_source_refs(request: Mapping[str, object]) -> list[dict[str, str]]:
    refs = [
        {"record_kind": str(record["record_kind"]), "source_sha256": str(record["source"]["sha256"])}
        for record in request.get("records", [])
        if isinstance(record, Mapping) and isinstance(record.get("source"), Mapping)
    ]
    return sorted(refs, key=lambda item: (item["record_kind"], item["source_sha256"]))


def _automatic_terminal_result(
    *,
    projection_id: str,
    generated_at: str,
    request_hash: str,
    source_refs: list[dict[str, str]],
    status: str,
    findings: list[Mapping[str, object]],
    before: str | None = None,
    after: str | None = None,
    public_ids: list[str] | None = None,
    planned_paths: list[str] | None = None,
    changed_paths: list[str] | None = None,
) -> dict[str, object]:
    """Build a validated automatic result when no human approval applies."""
    empty_request: dict[str, object] = {
        "generated_at": generated_at,
    }
    plan_data: dict[str, object] = {
        "projection_id": projection_id,
        "request_sha256": request_hash,
        "source_refs": source_refs,
        "before": before or sha256_hex([]),
        "findings": _dedupe_projection_findings(list(findings)),
        "public_ids": public_ids or [],
        "planned_paths": planned_paths or [],
    }
    result = _projection_result(
        empty_request,
        plan_data,
        status=status,
        approval_digest=None,
        findings=list(findings),
        public_ids=public_ids,
        planned_paths=planned_paths,
        changed_paths=changed_paths,
        before=before,
        after=after,
        human_gate="NOT_REQUIRED",
        projection_mode=AUTOMATIC_PLAN_MODE,
    )
    return result


def _automatic_summary(result: Mapping[str, object], *, request_locator: str | None) -> dict[str, object]:
    findings = result.get("findings", [])
    finding_codes = sorted({str(item.get("code")) for item in findings if isinstance(item, Mapping) and item.get("code")})
    projection_id = str(result.get("projection_id", ""))
    return {
        "command": "project-plan-automatic",
        "authority": "ORCHESTRATION_PLAN_READY",
        "projection_mode": AUTOMATIC_PLAN_MODE,
        "status": result.get("status"),
        "projection_id": projection_id,
        "record_count": len(result.get("source_refs", [])) if isinstance(result.get("source_refs"), list) else 0,
        "request_locator": request_locator,
        "result_locator": f"{projection_id}/public-projection-result.json",
        "request_sha256": result.get("request_sha256"),
        "public_ids": sorted({str(value) for value in result.get("public_ids", [])}),
        "planned_paths": sorted({str(value) for value in result.get("planned_paths", [])}),
        "changed_paths": sorted({str(value) for value in result.get("changed_paths", [])}),
        "finding_codes": finding_codes,
        "human_gate": result.get("human_gate", {}).get("status") if isinstance(result.get("human_gate"), Mapping) else "NOT_REQUIRED",
    }


def _automatic_safe_generated_at(source: Mapping[str, object]) -> str:
    generated_at = source.get("generated_at")
    if isinstance(generated_at, str) and _valid_timestamp(generated_at):
        return generated_at
    # The source should already be canonical.  This fallback keeps a malformed
    # source failure representable as closed result evidence without copying
    # an unsafe value into the result.
    return "1970-01-01T00:00:00Z"


def _automatic_safe_target_fingerprint(target: Path | None) -> str:
    if target is None:
        return sha256_hex([])
    try:
        return _tree_fingerprint(target)
    except PreparationError:
        return sha256_hex([])


def _automatic_batch_source_sha256(source: Mapping[str, object]) -> str | None:
    projects = source.get("projects")
    if not isinstance(projects, list) or not projects:
        return None
    entries: list[dict[str, str]] = []
    for project in projects:
        if not isinstance(project, Mapping):
            return None
        project_id = project.get("project_id")
        plan_hash = project.get("production_plan_markdown_sha256")
        if not isinstance(project_id, str) or not isinstance(plan_hash, str) or HASH64.fullmatch(plan_hash) is None:
            return None
        entries.append({"project_id": project_id, "production_plan_markdown_sha256": plan_hash})
    entries.sort(key=lambda item: item["project_id"])
    return sha256_hex({"projects": entries})


def _automatic_preparation_failure(
    source: Mapping[str, object],
    *,
    projection_id: str,
    error: PreparationError,
    public_projection_root: Path | None,
) -> dict[str, object]:
    """Persist a sanitized terminal result when source preparation is blocked.

    Candidate preparation validates the canonical production bytes before it
    can return a request.  A rejected body therefore has no request hash or
    candidate file to use for ordinary planning.  Still, the canonical run or
    batch must finish with an explicit policy/authority result rather than
    looking like an unhandled runtime failure.  The fallback hash is an
    opaque digest of stable source metadata and the closed finding code; no
    source path, body, or exception text is copied.
    """
    policy_codes = PROJECTION_POLICY_CODES | {
        "CREDENTIAL",
        "PRIVATE_URL",
        "ABSOLUTE_PATH",
        "FORBIDDEN_ARTIFACT",
        "INTERNAL_REFERENCE",
    }
    authority_codes = {
        "AUTHORITY_INVALID",
        "DESTINATION_MISMATCH",
        "PROVENANCE_MISSING",
        "SOURCE_INVALID",
        "SOURCE_UNAVAILABLE",
    }
    if error.code in policy_codes:
        finding_code = error.code
        status = "BLOCKED_POLICY"
    elif error.code in authority_codes:
        finding_code = "AUTHORITY_INVALID"
        status = "BLOCKED_POLICY"
    else:
        finding_code = "LAYOUT_INVALID"
        status = "BLOCKED_CONFLICT"
    finding = _projection_finding(finding_code, str(error.location), error.remediation)
    request_hash = sha256_hex({
        "authority": "automatic-plan-preparation-failure/v1",
        "projection_id": projection_id,
        "source_status": source.get("status"),
        "source_plan_sha256": source.get("production_plan_sha256"),
        "finding_code": finding_code,
    })
    before = _automatic_safe_target_fingerprint(public_projection_root)
    result = _automatic_terminal_result(
        projection_id=projection_id,
        generated_at=_automatic_safe_generated_at(source),
        request_hash=request_hash,
        source_refs=[],
        status=status,
        findings=[finding],
        before=before,
        after=before,
    )
    return result


def _automatic_report_resolution(
    source: Mapping[str, object],
    *,
    internal_output_root: Path,
    public_projection_root: Path | None,
    state_root: Path,
    expected_status: str,
) -> tuple[str, Path | None]:
    """Bind automatic projection to the source's exact resolved destinations."""
    run_id = source.get("run_id")
    if not isinstance(run_id, str) or STABLE_ID.fullmatch(run_id) is None:
        raise _prepare_error("AUTHORITY_INVALID", "source.run_id", "use the stable run or batch identifier emitted by orchestration")
    if source.get("status") != expected_status:
        raise _prepare_error("AUTHORITY_INVALID", "source.status", f"automatic plan projection requires {expected_status}")
    resolution = source.get("destination_resolution")
    if not isinstance(resolution, Mapping):
        raise _prepare_error("AUTHORITY_INVALID", "source.destination_resolution", "automatic plan projection requires the exact resolved destination profile")
    authority = source.get("automatic_plan_authority")
    if not isinstance(authority, Mapping):
        raise _prepare_error("AUTHORITY_INVALID", "source.automatic_plan_authority", "use the authority envelope emitted by the canonical run or batch producer")
    source_sha256 = source.get("production_plan_sha256") if expected_status == "PLAN_READY" else _automatic_batch_source_sha256(source)
    if not isinstance(source_sha256, str) or HASH64.fullmatch(source_sha256) is None:
        raise _prepare_error("AUTHORITY_INVALID", "source.automatic_plan_authority.source_sha256", "retain the canonical production plan hash set")
    try:
        expected_authority = build_automatic_plan_authority(
            producer="tools/run.py" if expected_status == "PLAN_READY" else "tools/batch_run.py",
            source_status=expected_status,
            source_id=run_id,
            source_sha256=source_sha256,
            destination_resolution=resolution,
        )
    except ValueError as exc:
        raise _prepare_error("AUTHORITY_INVALID", "source.automatic_plan_authority", "repair the canonical automatic plan authority envelope") from exc
    if dict(authority) != expected_authority:
        raise _prepare_error("AUTHORITY_INVALID", "source.automatic_plan_authority", "use the unmodified authority envelope emitted with this source result")
    _assert_report_resolution(source, internal_output_root.expanduser().resolve(strict=False), run_id)
    resolved_state = _optional_resolution_role(resolution, "state_root")
    if resolved_state is None or resolved_state != state_root.expanduser().resolve(strict=False):
        raise _prepare_error("AUTHORITY_INVALID", "source.destination_resolution.state_root", "use the state_root from the same resolved destination profile")
    configured_public = _optional_resolution_role(resolution, "public_projection_root")
    supplied_public = public_projection_root.expanduser().resolve(strict=False) if public_projection_root is not None else None
    if supplied_public is not None and configured_public != supplied_public:
        raise _prepare_error("AUTHORITY_INVALID", "source.destination_resolution.public_projection_root", "automatic projection may use only the profile's configured public_projection_root")
    return run_id, configured_public


def _automatic_request_guard(
    request: Mapping[str, object],
    *,
    projection_id: str,
    expected_record_count: int | None = None,
) -> list[dict[str, str]]:
    """Keep the automatic authority restricted to the source plan set."""
    findings: list[dict[str, str]] = []
    records = request.get("records")
    if not isinstance(records, list) or not records:
        return [_projection_finding("AUTHORITY_INVALID", "request.records", "automatic projection requires at least one canonical production plan")]
    if expected_record_count is not None and len(records) != expected_record_count:
        findings.append(_projection_finding("AUTHORITY_INVALID", "request.records", "the automatic request must contain every completed plan exactly once"))
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            findings.append(_projection_finding("AUTHORITY_INVALID", f"request.records[{index}]", "automatic projection accepts only plan records"))
            continue
        if record.get("record_kind") != "plan":
            findings.append(_projection_finding("AUTHORITY_INVALID", f"request.records[{index}].record_kind", "automatic projection accepts only plan records"))
        source = record.get("source")
        if not isinstance(source, Mapping) or source.get("run_id") != projection_id:
            findings.append(_projection_finding("AUTHORITY_INVALID", f"request.records[{index}].source.run_id", "bind every record to the originating PLAN_READY or PASSED run"))
    return _dedupe_projection_findings(findings)


def _project_automatic_request(
    request: Mapping[str, object],
    *,
    request_locator: str,
    internal_output_root: Path,
    public_projection_root: Path,
    state_root: Path,
    authority_findings: list[Mapping[str, object]] | None = None,
    authority_validated: bool = False,
    fail_after: int | None = None,
) -> dict[str, object]:
    """Apply a producer-bound plan request without accepting a public-share approval."""
    request_hash = request_sha256(request)
    authority_findings = list(authority_findings or [])
    if not authority_validated:
        authority_findings.append(_projection_finding(
            "AUTHORITY_INVALID",
            "automatic_plan_authority",
            "call automatic projection only through the canonical PLAN_READY or PASSED producer",
        ))
    if authority_findings:
        result = _automatic_terminal_result(
            projection_id=str(request.get("projection_id")),
            generated_at=str(request.get("generated_at")),
            request_hash=request_hash,
            source_refs=_request_source_refs(request),
            status="BLOCKED_POLICY",
            findings=authority_findings,
        )
        _write_projection_result(state_root, str(request["projection_id"]), result, allow_transition=True)
        return result

    plan_data = _projection_plan_data(
        request,
        internal_output_root=internal_output_root.expanduser().resolve(strict=False),
        public_projection_root=public_projection_root.expanduser().resolve(strict=False),
    )
    findings = list(plan_data["findings"])
    if _replay_dirty_target_allowed(public_projection_root, plan_data):
        findings = [finding for finding in findings if finding.get("code") != "TARGET_DIRTY"]
    findings = _dedupe_projection_findings(findings)

    if any(finding.get("code") in PROJECTION_POLICY_CODES for finding in findings):
        result = _projection_result(
            request,
            plan_data,
            status="BLOCKED_POLICY",
            approval_digest=None,
            findings=findings,
            public_ids=[],
            planned_paths=[],
            human_gate="NOT_REQUIRED",
            projection_mode=AUTOMATIC_PLAN_MODE,
        )
        _write_projection_result(state_root, str(plan_data["projection_id"]), result, allow_transition=True)
        return result
    if any(finding.get("code") in {"TARGET_CONFLICT", "TARGET_DIRTY", "LAYOUT_INVALID"} for finding in findings):
        result = _projection_result(
            request,
            plan_data,
            status="BLOCKED_CONFLICT",
            approval_digest=None,
            findings=findings,
            public_ids=[],
            planned_paths=[],
            human_gate="NOT_REQUIRED",
            projection_mode=AUTOMATIC_PLAN_MODE,
        )
        _write_projection_result(state_root, str(plan_data["projection_id"]), result, allow_transition=True)
        return result

    plans = [plan for plan in plan_data.get("plans", []) if isinstance(plan, Mapping)]
    if not plans or not all(isinstance(plan.get("expected_files"), Mapping) for plan in plans):
        result = _projection_result(
            request,
            plan_data,
            status="BLOCKED_CONFLICT",
            approval_digest=None,
            findings=[*findings, _projection_finding("LAYOUT_INVALID", "projection.plan", "produce a complete automatic plan projection before applying")],
            public_ids=[],
            planned_paths=[],
            human_gate="NOT_REQUIRED",
            projection_mode=AUTOMATIC_PLAN_MODE,
        )
        _write_projection_result(state_root, str(plan_data["projection_id"]), result, allow_transition=True)
        return result

    planned_files: dict[str, bytes] = {}
    for plan in plans:
        if plan.get("is_new"):
            expected_files = plan.get("expected_files")
            if isinstance(expected_files, Mapping):
                planned_files.update({str(path): content for path, content in expected_files.items() if isinstance(path, str) and isinstance(content, bytes)})
    target_updates = plan_data.get("target_updates", {}) if isinstance(plan_data.get("target_updates"), Mapping) else {}
    if not planned_files and not target_updates:
        transaction = {"outcome": "ALREADY_PROJECTED", "changed_paths": [], "after": str(plan_data["before"]), "findings": []}
    else:
        transaction = _apply_projection_transaction(
            public_projection_root,
            before=str(plan_data["before"]),
            planned_files=planned_files,
            target_updates=target_updates,
            fail_after=fail_after,
        )
    status = str(transaction["outcome"])
    result = _projection_result(
        request,
        plan_data,
        status=status,
        approval_digest=None,
        findings=[*findings, *list(transaction.get("findings", []))],
        public_ids=plan_data.get("public_ids", []) if status in {"APPLIED", "ALREADY_PROJECTED", "FAILED"} else [],
        planned_paths=plan_data.get("planned_paths", []) if status in {"APPLIED", "FAILED"} else [],
        changed_paths=transaction.get("changed_paths", []) if isinstance(transaction.get("changed_paths"), list) else [],
        before=str(plan_data["before"]),
        after=str(transaction.get("after", plan_data["before"])),
        human_gate="NOT_REQUIRED",
        projection_mode=AUTOMATIC_PLAN_MODE,
        extra_remediations=list(transaction.get("remediations", [])) if isinstance(transaction.get("remediations"), list) else [],
    )
    _write_projection_result(state_root, str(plan_data["projection_id"]), result, allow_transition=True)
    return result


def project_plan_automatic(
    report: Mapping[str, object],
    *,
    internal_output_root: Path,
    public_projection_root: Path | None,
    state_root: Path,
    projection_id: str | None = None,
    fail_after: int | None = None,
) -> dict[str, object]:
    """Project one canonical PLAN_READY production plan to its configured target."""
    from tools.canonical_plan_projection import project_attested
    if projection_id is not None and projection_id != report.get("run_id"):
        raise _prepare_error("AUTHORITY_INVALID", "projection_id", "projection ID must match the canonical source run")
    return project_attested(report, internal_output_root=internal_output_root, public_projection_root=public_projection_root, state_root=state_root, fail_after=fail_after)


def project_batch_automatic(
    summary: Mapping[str, object],
    *,
    internal_output_root: Path,
    public_projection_root: Path | None,
    state_root: Path,
    projection_id: str | None = None,
    fail_after: int | None = None,
) -> dict[str, object]:
    """Project every plan in one canonical PASSED batch as one transaction."""
    from tools.canonical_plan_projection import project_attested
    if projection_id is not None and projection_id != summary.get("run_id"):
        raise _prepare_error("AUTHORITY_INVALID", "projection_id", "projection ID must match the canonical batch")
    return project_attested(summary, internal_output_root=internal_output_root, public_projection_root=public_projection_root, state_root=state_root, batch=True, fail_after=fail_after)


def _load_document(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PublicProjectionError(_error(f"cannot read {path.name}: {exc}", "supply a UTF-8 JSON or YAML contract file")) from exc


def _prepare_stdout(result: Mapping[str, object]) -> dict[str, object]:
    """Render only non-sensitive prepare metadata to stdout."""
    return {
        "command": "prepare",
        "status": result.get("status"),
        "projection_id": result.get("projection_id"),
        "record_count": result.get("record_count", 0),
        "request_locator": result.get("request_locator"),
        "finding_codes": sorted({str(code) for code in result.get("finding_codes", [])}),
        "work_status": result.get("work_status", "NOT_AVAILABLE"),
    }


def _projection_stdout(result: Mapping[str, object]) -> dict[str, object]:
    """Render only stable, non-sensitive plan/init metadata to stdout."""
    findings = result.get("findings", [])
    finding_codes = result.get("finding_codes", [])
    if isinstance(findings, list):
        finding_codes = [item.get("code") for item in findings if isinstance(item, Mapping)]
    return {
        "command": result.get("command", "project"),
        "status": result.get("status"),
        "projection_id": result.get("projection_id"),
        "record_count": result.get("record_count", len(result.get("source_refs", [])) if isinstance(result.get("source_refs"), list) else 0),
        "public_ids": sorted({str(value) for value in result.get("public_ids", [])}),
        "planned_paths": sorted({str(value) for value in result.get("planned_paths", [])}),
        "finding_codes": sorted({str(value) for value in finding_codes if value}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate, prepare, or safely plan a public projection")
    parser.add_argument("command", choices=["validate", "prepare", "init-target", "project"])
    parser.add_argument("--layout", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--run-report", type=Path)
    parser.add_argument("--batch-summary", type=Path)
    parser.add_argument("--refresh", type=Path)
    parser.add_argument("--projection-id")
    parser.add_argument("--destinations-file", type=Path)
    parser.add_argument("--target-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "validate" and not any((args.layout, args.request, args.approval, args.result)):
        parser.error("validate requires at least one contract input")
    if args.command == "prepare":
        sources = [args.run_report, args.batch_summary, args.refresh]
        if sum(value is not None for value in sources) != 1:
            parser.error("prepare requires exactly one of --run-report, --batch-summary, or --refresh")
        if args.destinations_file is None:
            parser.error("prepare requires --destinations-file")
        if (args.run_report is not None or args.batch_summary is not None) and not args.projection_id:
            parser.error("prepare requires --projection-id for --run-report and --batch-summary")
    if args.command in {"init-target", "project"}:
        if args.destinations_file is None:
            parser.error(f"{args.command} requires --destinations-file")
        if args.dry_run == args.apply:
            parser.error(f"{args.command} requires exactly one of --dry-run or --apply")
    if args.command == "init-target" and args.request is not None:
        parser.error("init-target does not accept --request")
    if args.command == "init-target" and args.projection_id is not None:
        parser.error("init-target does not accept --projection-id")
    if args.command == "project":
        if args.request is None:
            parser.error("project requires --request")
        if args.approval is not None:
            if args.dry_run:
                parser.error("project --dry-run does not consume an approval file")
    try:
        if args.command == "prepare":
            if args.run_report is not None:
                report = _load_document(args.run_report)
                if not isinstance(report, Mapping) or not isinstance(report.get("run_id"), str):
                    raise _prepare_error("SOURCE_INVALID", "run-report", "provide a run report with a stable run_id")
                _resolution, root = _prepare_resolution(args.destinations_file, str(report["run_id"]))
                result = prepare_run_report(report, internal_output_root=root, projection_id=args.projection_id)
            elif args.batch_summary is not None:
                summary = _load_document(args.batch_summary)
                if not isinstance(summary, Mapping) or not isinstance(summary.get("run_id"), str):
                    raise _prepare_error("SOURCE_INVALID", "batch-summary", "provide a batch summary with a stable run_id")
                _resolution, root = _prepare_resolution(args.destinations_file, str(summary["run_id"]))
                result = prepare_batch_summary(summary, internal_output_root=root, projection_id=args.projection_id)
            else:
                request_path = args.refresh.expanduser().resolve(strict=False)
                request_document = _load_document(request_path)
                if not isinstance(request_document, Mapping) or not isinstance(request_document.get("projection_id"), str):
                    raise _prepare_error("SOURCE_INVALID", "refresh.request", "provide a request with a stable projection_id")
                _resolution, root = _prepare_resolution(args.destinations_file, str(request_document["projection_id"]))
                result = refresh_request(request_path, internal_output_root=root)
            print(json.dumps(_prepare_stdout(result), ensure_ascii=False, sort_keys=True))
            return 0 if result.get("status") in PREPARE_STATUSES else 2
        if args.command == "init-target":
            resolution = _projection_resolution(args.destinations_file, "INIT-TARGET", target_root=args.target_root)
            result = init_target(_resolution_role(resolution, "public_projection_root"), apply=args.apply)
            print(json.dumps(_projection_stdout(result), ensure_ascii=False, sort_keys=True))
            return 0 if result.get("status") in INIT_STATUSES else 2
        if args.command == "project":
            request_path = args.request.expanduser().resolve(strict=False)
            request_document = _load_document(request_path)
            if not isinstance(request_document, Mapping) or not isinstance(request_document.get("projection_id"), str):
                raise _prepare_error("SOURCE_INVALID", "request", "provide a request with a stable projection_id")
            projection_id = str(request_document["projection_id"])
            resolution = _projection_resolution(args.destinations_file, projection_id, target_root=args.target_root)
            if args.apply:
                result = project_apply(
                    request_path,
                    approval_path=args.approval,
                    internal_output_root=_resolution_role(resolution, "internal_output_root"),
                    public_projection_root=_resolution_role(resolution, "public_projection_root"),
                    state_root=_resolution_role(resolution, "state_root"),
                )
            else:
                result = project_dry_run(
                    request_path,
                    internal_output_root=_resolution_role(resolution, "internal_output_root"),
                    public_projection_root=_resolution_role(resolution, "public_projection_root"),
                    state_root=_resolution_role(resolution, "state_root"),
                )
            print(json.dumps(_projection_stdout(result), ensure_ascii=False, sort_keys=True))
            return 0 if result.get("status") in {"DRY_RUN_READY", "APPLIED", "ALREADY_PROJECTED"} else 2
        values = {
            "layout": _load_document(args.layout) if args.layout else None,
            "request": _load_document(args.request) if args.request else None,
            "approval": _load_document(args.approval) if args.approval else None,
            "result": _load_document(args.result) if args.result else None,
        }
        errors = validate_contracts(**values)
    except PreparationError as exc:
        if args.command in {"init-target", "project"}:
            output = {
                "command": args.command,
                "status": "FAILED",
                "projection_id": args.projection_id,
                "record_count": 0,
                "public_ids": [],
                "planned_paths": [],
                "finding_codes": [exc.code],
            }
            print(json.dumps(output, ensure_ascii=False, sort_keys=True))
            return 2
        output = {
            "command": "prepare",
            "status": "FAILED",
            "projection_id": args.projection_id,
            "record_count": 0,
            "request_locator": None,
            "finding_codes": [exc.code],
            "work_status": "NOT_AVAILABLE",
        }
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 2
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
