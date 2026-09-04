#!/usr/bin/env python3
"""Resolve Git-external orchestration destinations through one closed contract.

The resolver is intentionally independent of runtime commands.  Runtime wiring
is a later task; this module owns the profile format, precedence, canonical
resolution evidence, and write-boundary checks used by those commands.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Iterable, Mapping

import yaml

from tools.validate import _schema_errors, load_json


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DESTINATIONS_SCHEMA = ROOT / "schemas/output-destinations.schema.json"
DESTINATION_RESOLUTION_SCHEMA = ROOT / "schemas/destination-resolution.schema.json"
CONTRACT_VERSION = "output-destinations/v1"
RESOLUTION_VERSION = "destination-resolution/v1"
ENVIRONMENT_FILE = "AGENTIC_ART_DESTINATIONS_FILE"
ROLES = ("state_root", "internal_output_root", "public_projection_root")
REQUIRED_ROLES = ("state_root", "internal_output_root")
SOURCE_NAMES = {"direct-cli", "profile", "legacy-default"}
CONFIG_SOURCES = {"cli-file", "environment-file", "legacy-defaults"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}(?:/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}){0,3}$")
PROFILE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")


class DestinationError(ValueError):
    """A destination profile or derived path cannot be accepted safely."""


def _error(detail: str, remediation: str) -> DestinationError:
    return DestinationError(f"output-destinations: {detail}; remediation: {remediation}")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_resolution_bytes(resolution: Mapping[str, object]) -> bytes:
    """Return the stable bytes used to compare two resolution results."""
    if not isinstance(resolution, Mapping):
        raise _error("resolution evidence must be a mapping", "pass the destination-resolution/v1 object")
    return _canonical_json(dict(resolution))


def resolution_sha256(resolution: Mapping[str, object]) -> str:
    return _sha256_bytes(canonical_resolution_bytes(resolution))


def destinations_profile_selected(
    destinations_file: str | Path | None,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether the caller explicitly selected the destination profile path."""
    selected_environment = os.environ if environment is None else environment
    # An empty environment value is still an explicit selection and must fail
    # closed in ``resolve_destinations`` rather than silently falling back.
    return destinations_file is not None or ENVIRONMENT_FILE in selected_environment


def _as_text(value: object, label: str) -> str:
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value:
        raise _error(f"{label} is empty or not a string", "provide a non-empty path")
    if "\x00" in value:
        raise _error(f"{label} contains NUL", "remove control characters from the path")
    return value


def _profile_errors(profile: object, source: str) -> list[str]:
    try:
        schema = load_json(OUTPUT_DESTINATIONS_SCHEMA)
    except ValueError as exc:
        return [f"{source}: schema unavailable: {exc}"]
    return _schema_errors(profile, schema, source)


def load_destinations_file(path: str | Path) -> tuple[dict[str, object], str]:
    """Load and schema-check one explicitly selected profile file.

    The returned hash is over the exact UTF-8 bytes read.  The file path is
    deliberately not returned as evidence, so absolute local paths do not
    become part of a tracked report.
    """
    raw_path = _as_text(path, "destinations file")
    profile_path = Path(raw_path).expanduser()
    if not profile_path.is_absolute():
        raise _error("destinations file must be absolute", "pass an absolute path to an external profile")
    try:
        profile_path = profile_path.resolve(strict=True)
        raw = profile_path.read_bytes()
    except (OSError, RuntimeError) as exc:
        raise _error("destinations file cannot be read", "repair the selected external profile and retry") from exc
    if not profile_path.is_file():
        raise _error("destinations file is not a regular file", "select a regular YAML profile file")
    try:
        value = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise _error("destinations file is not valid UTF-8 YAML", "repair the closed YAML profile") from exc
    errors = _profile_errors(value, "output-destinations/v1")
    if errors:
        raise _error("profile is invalid: " + " | ".join(errors), "satisfy the closed output-destinations/v1 schema")
    return value, _sha256_bytes(raw)


def _selected_profile(
    destinations_file: str | Path | None,
    environment: Mapping[str, str],
) -> tuple[dict[str, object] | None, str, str]:
    if destinations_file is not None:
        profile, digest = load_destinations_file(destinations_file)
        return profile, "cli-file", digest
    environment_path = environment.get(ENVIRONMENT_FILE)
    if environment_path is not None:
        if not isinstance(environment_path, str) or not environment_path:
            raise _error(
                f"{ENVIRONMENT_FILE} is empty",
                "unset it or point it to an external output-destinations/v1 file",
            )
        profile, digest = load_destinations_file(environment_path)
        return profile, "environment-file", digest
    return None, "legacy-defaults", _sha256_bytes(b"legacy-defaults\n")


def _validate_direct(direct: Mapping[str, object] | None) -> dict[str, object]:
    if direct is None:
        return {}
    if not isinstance(direct, Mapping):
        raise _error("direct paths must be a mapping", "pass role names to direct CLI values")
    unknown = sorted(set(direct) - set(ROLES))
    if unknown:
        raise _error(f"direct paths contain unknown roles {unknown}", "use only the three declared destination roles")
    return dict(direct)


def _validate_legacy(legacy_defaults: Mapping[str, object] | None) -> dict[str, object]:
    if legacy_defaults is None:
        return {}
    if not isinstance(legacy_defaults, Mapping):
        raise _error("legacy defaults must be a mapping", "pass the command's existing defaults by role")
    unknown = sorted(set(legacy_defaults) - set(ROLES))
    if unknown:
        raise _error(f"legacy defaults contain unknown roles {unknown}", "use only the three declared destination roles")
    return dict(legacy_defaults)


def _normalise_root(
    value: object,
    label: str,
    repository_root: Path,
    child_roots: tuple[Path, ...],
) -> Path:
    text = _as_text(value, label)
    expanded = Path(text).expanduser()
    if not expanded.is_absolute():
        raise _error(f"{label} must be absolute", "use an absolute Git-external directory")
    try:
        resolved = expanded.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise _error(f"{label} cannot be resolved", "repair the path or its symlink parents") from exc
    if resolved == Path(resolved.anchor):
        raise _error(f"{label} cannot be the filesystem root", "use a dedicated external directory")
    if resolved == repository_root or repository_root in resolved.parents:
        raise _error(f"{label} is inside the orchestration repository", "choose a Git-external directory")
    for child_root in child_roots:
        if resolved == child_root or child_root in resolved.parents:
            raise _error(f"{label} is inside a child checkout", "choose a path outside every manifest checkout")
    if resolved.exists() and not resolved.is_dir():
        raise _error(f"{label} exists but is not a directory", "choose a directory or a not-yet-created path")
    return resolved


def _assert_non_overlapping(destinations: Mapping[str, Path]) -> None:
    present = [(role, path) for role, path in destinations.items() if path is not None]
    for index, (left_role, left) in enumerate(present):
        for right_role, right in present[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise _error(
                    f"{left_role} and {right_role} overlap",
                    "give each destination role a separate root with no ancestor relationship",
                )


def _direct_digest(direct: Mapping[str, object]) -> str:
    serialised = {key: str(value) for key, value in sorted(direct.items()) if value is not None}
    return _sha256_bytes(_canonical_json({"direct": serialised}))


def _safe_context(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    pattern = PROJECT_ID_PATTERN if label == "project_id" else ID_PATTERN
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _error(f"{label} is unsafe", "use a path-safe identifier without separators or traversal")
    return value


def resolve_destinations(
    destinations_file: str | Path | None = None,
    *,
    direct: Mapping[str, object] | None = None,
    direct_paths: Mapping[str, object] | None = None,
    environment: Mapping[str, str] | None = None,
    legacy_defaults: Mapping[str, object] | None = None,
    repository_root: str | Path | None = None,
    child_roots: Iterable[str | Path] = (),
    run_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, object]:
    """Resolve all roles with fixed precedence and return internal evidence.

    ``direct`` is the adapter-facing representation of direct CLI arguments.
    ``direct_paths`` is accepted as a descriptive alias; callers must not pass
    both.  No local config filename is searched implicitly.
    """
    if direct is not None and direct_paths is not None:
        raise _error("direct and direct_paths were both supplied", "pass one direct CLI mapping")
    selected_direct = _validate_direct(direct if direct is not None else direct_paths)
    selected_environment = dict(os.environ if environment is None else environment)
    selected_legacy = _validate_legacy(legacy_defaults)
    profile, config_source, config_digest = _selected_profile(destinations_file, selected_environment)
    profile_destinations = profile.get("destinations", {}) if profile is not None else {}
    if not isinstance(profile_destinations, Mapping):  # schema validation makes this unreachable, keep the boundary explicit
        raise _error("profile destinations are not a mapping", "repair the closed profile")

    if config_source == "legacy-defaults" and selected_direct:
        config_source = "cli-file"
        config_digest = _direct_digest(selected_direct)

    root = (Path(repository_root) if repository_root is not None else ROOT).expanduser().resolve()
    normalised_children = tuple(Path(path).expanduser().resolve() for path in child_roots)
    values: dict[str, Path | None] = {}
    sources: dict[str, str] = {}
    for role in ROLES:
        if role in selected_direct and selected_direct[role] is not None:
            raw_value = selected_direct[role]
            source = "direct-cli"
        elif role in profile_destinations:
            raw_value = profile_destinations[role]
            source = "profile"
        elif role in selected_legacy:
            raw_value = selected_legacy[role]
            source = "legacy-default"
        else:
            raw_value = None
            source = ""
        if raw_value is None:
            if role in REQUIRED_ROLES:
                raise _error(
                    f"{role} has no value",
                    "provide a direct CLI path, an explicit profile, or the legacy required argument",
                )
            continue
        values[role] = _normalise_root(raw_value, role, root, normalised_children)
        sources[role] = source
    _assert_non_overlapping(values)

    safe_run_id = _safe_context(run_id, "run_id")
    safe_project_id = _safe_context(project_id, "project_id")
    evidence_destinations = {
        role: {"path": str(values[role]), "source": sources[role]}
        for role in ROLES
        if role in values and values[role] is not None
    }
    result: dict[str, object] = {
        "contract_version": RESOLUTION_VERSION,
        "profile": profile.get("profile", "legacy") if profile is not None else "legacy",
        "config_source": config_source,
        "config_sha256": config_digest,
        "run_id": safe_run_id,
        "project_id": safe_project_id,
        "destinations": evidence_destinations,
        "classification": "PROJECT_INTERNAL",
    }
    errors = _schema_errors(result, load_json(DESTINATION_RESOLUTION_SCHEMA), "destination-resolution")
    if errors:
        raise _error("resolver produced invalid evidence: " + " | ".join(errors), "preserve destination-resolution/v1")
    return result


def resolve_run_destination(root: str | Path, *components: str) -> Path:
    """Derive one run/project path without permitting traversal or aliases."""
    if not components:
        raise _error("derived destination needs at least one component", "supply a validated run or project ID")
    base = Path(root).expanduser().resolve(strict=False)
    for index, component in enumerate(components):
        if not isinstance(component, str) or ID_PATTERN.fullmatch(component) is None:
            raise _error(
                f"derived component {index} is unsafe",
                "use one path-safe run/project identifier without separators or traversal",
            )
    candidate = base.joinpath(*components).resolve(strict=False)
    if candidate == base or base not in candidate.parents:
        raise _error("derived destination escapes its root", "keep every derived component below the resolved root")
    return candidate


def manifest_child_roots(manifest: Mapping[str, object], workspace_root: str | Path) -> tuple[Path, ...]:
    """Derive manifest checkout roots for the resolver's repository boundary guard."""
    repositories = manifest.get("repositories") if isinstance(manifest, Mapping) else None
    if not isinstance(repositories, list):
        raise _error("manifest repositories are unavailable", "load the manifest before resolving runtime destinations")
    base = Path(workspace_root).expanduser().resolve(strict=False)
    roots: list[Path] = []
    for index, repository in enumerate(repositories):
        if not isinstance(repository, Mapping) or not isinstance(repository.get("path"), str):
            raise _error(
                f"manifest repository {index} has no safe path",
                "derive child checkout roots from repositories.yaml",
            )
        path = Path(str(repository["path"]))
        if path.is_absolute():
            raise _error("manifest child path is absolute", "use repository-relative manifest paths")
        roots.append((base / path).resolve(strict=False))
    return tuple(roots)


def write_resolution_evidence(
    state_root: str | Path,
    run_id: str,
    resolution: Mapping[str, object],
) -> Path:
    """Create one stable resolution file without replacing an existing result."""
    errors = validate_destination_resolution(resolution)
    if errors:
        raise _error("resolution evidence is invalid: " + " | ".join(errors), "pass destination-resolution/v1 from this resolver")
    target = resolve_run_destination(state_root, run_id) / "destination-resolution.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(dict(resolution), ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    if target.exists():
        try:
            if target.is_file() and target.read_bytes() == rendered:
                return target
        except OSError as exc:
            raise _error("existing resolution evidence is unreadable", "inspect the run-scoped evidence before resuming") from exc
        raise _error("existing resolution evidence conflicts", "resume with the same profile and run ID or choose a new run ID")

    temporary = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Linking the completed temporary file is atomic and never replaces
            # a file created concurrently by another runtime invocation.
            os.link(temporary, target)
        except FileExistsError:
            if target.is_file() and target.read_bytes() == rendered:
                return target
            raise _error("concurrent resolution evidence conflicts", "resume with the same profile and run ID or choose a new run ID")
        return target
    except FileExistsError as exc:
        raise _error("atomic temporary evidence path already exists", "remove only the stale run-scoped temporary file") from exc
    except OSError as exc:
        raise _error("resolution evidence could not be written atomically", "repair the external state directory and retry") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def assert_create_only_directory(path: str | Path, *, label: str = "derived destination") -> Path:
    """Allow a missing or empty directory, never an existing populated target."""
    candidate = Path(path).expanduser().resolve(strict=False)
    if candidate.exists() and not candidate.is_dir():
        raise _error(f"{label} is not a directory", "choose a missing or directory destination")
    if candidate.is_dir():
        try:
            if any(candidate.iterdir()):
                raise _error(f"{label} is not empty", "use a new run-scoped destination; do not overwrite existing output")
        except OSError as exc:
            raise _error(f"{label} cannot be inspected", "repair directory access before writing") from exc
    return candidate


def validate_destination_profile(value: object, source: str = "output-destinations") -> list[str]:
    """Expose the closed-profile validator for parent validation and tests."""
    return _profile_errors(value, source)


def validate_destination_resolution(value: object, source: str = "destination-resolution") -> list[str]:
    try:
        schema = load_json(DESTINATION_RESOLUTION_SCHEMA)
    except ValueError as exc:
        return [f"{source}: schema unavailable: {exc}"]
    return _schema_errors(value, schema, source)
