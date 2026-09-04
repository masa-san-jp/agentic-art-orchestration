#!/usr/bin/env python3
"""Validate the closed, metadata-only public projection contracts.

This contract-stage tool does not read or mutate a public target.  The later
prepare, plan, and apply tasks own filesystem projection; keeping this module
validation-only makes an accidental public write impossible at this stage.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
import re
import stat
import sys
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
) -> tuple[dict[str, object], str, bytes]:
    if record_kind not in {"plan", "work"}:
        raise _prepare_error("SOURCE_UNAVAILABLE", f"records[{index}]", "prepare only a declared plan or an available work manifest")
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
        "rights_status": "unknown",
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
            "visibility": "unknown",
            "rights_status": "unknown",
            "consent_status": "unknown",
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


def prepare_run_report(report: Mapping[str, object], *, internal_output_root: Path, projection_id: str | None = None) -> dict[str, object]:
    """Produce one internal draft request from a completed PLAN_READY run."""
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


def prepare_batch_summary(summary: Mapping[str, object], *, internal_output_root: Path, projection_id: str | None = None) -> dict[str, object]:
    """Produce one deterministic internal draft request from a PASSED batch."""
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare or validate public projection contracts without touching a public target")
    parser.add_argument("command", choices=["validate", "prepare"])
    parser.add_argument("--layout", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--run-report", type=Path)
    parser.add_argument("--batch-summary", type=Path)
    parser.add_argument("--refresh", type=Path)
    parser.add_argument("--projection-id")
    parser.add_argument("--destinations-file", type=Path)
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
        values = {
            "layout": _load_document(args.layout) if args.layout else None,
            "request": _load_document(args.request) if args.request else None,
            "approval": _load_document(args.approval) if args.approval else None,
            "result": _load_document(args.result) if args.result else None,
        }
        errors = validate_contracts(**values)
    except PreparationError as exc:
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
