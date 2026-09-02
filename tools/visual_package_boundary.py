"""Parent-side acceptance boundary for the Production visual package.

The Production repository owns the visual-package schema and generator.  The
parent only accepts the metadata needed for cross-repository evidence and
checks the Git-external output files without copying their bodies into Git.
"""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
from typing import Any, Mapping


SHA40 = re.compile(r"^[0-9a-f]{40}$")
HASH64 = re.compile(r"^sha256:[0-9a-f]{64}$")
FORBIDDEN = re.compile(r"(?i)(PRIVATE_RAW|RESTRICTED|credential|raw[_ -]?(asset|conversation|voice)|signed[_ -]?url)")
BOARD_RELATIVE_PATH = "03_plan/visual-package/visual-reference-board.svg"
MOCKUP_RELATIVE_PATH = "03_plan/visual-package/concept-mockup.svg"


class VisualPackageBoundaryError(RuntimeError):
    """A visual package cannot be accepted without weakening the boundary."""


def _digest(value: object) -> str:
    payload = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")) or "\\" in value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _scan_forbidden(value: object, path: str = "$") -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if FORBIDDEN.search(str(key)):
                return f"{path}.{key}"
            found = _scan_forbidden(child, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _scan_forbidden(child, f"{path}[{index}]")
            if found:
                return found
    elif isinstance(value, str) and FORBIDDEN.search(value):
        return path
    return None


def validate_visual_package_boundary(
    package: object,
    *,
    project_root: Path,
    markdown_path: Path,
    production_commit: str,
    run_id: str,
    fixture_only: bool = False,
) -> list[str]:
    """Return sanitized acceptance findings for a child-owned package."""

    errors: list[str] = []
    if not isinstance(package, Mapping):
        return ["visual package must be a mapping"]
    forbidden = _scan_forbidden(package)
    if forbidden:
        errors.append(f"visual package contains a forbidden marker at {forbidden}")
    if package.get("status") != "READY":
        errors.append("visual package is not READY")
    if not isinstance(production_commit, str) or not SHA40.fullmatch(production_commit):
        errors.append("Production source commit is missing or malformed")
    if not isinstance(run_id, str) or not run_id.startswith("PURPOSE-E2E:"):
        errors.append("visual package evidence run_id is not scoped")

    for key, expected_kind, expected_path in (
        ("board", "BOARD", BOARD_RELATIVE_PATH),
        ("mockup", "MOCKUP", MOCKUP_RELATIVE_PATH),
    ):
        item = package.get(key)
        if not isinstance(item, Mapping):
            errors.append(f"visual package {key} is missing")
            continue
        if item.get("kind") != expected_kind:
            errors.append(f"visual package {key} kind is invalid")
        relative = item.get("relative_path")
        if relative != expected_path or not _safe_relative(relative):
            errors.append(f"visual package {key} relative link is invalid")
            continue
        asset_ref = item.get("asset_ref")
        if not isinstance(asset_ref, Mapping):
            errors.append(f"visual package {key} asset reference is missing")
            continue
        asset_hash = asset_ref.get("sha256")
        if not isinstance(asset_hash, str) or not HASH64.fullmatch(asset_hash):
            errors.append(f"visual package {key} asset hash is missing or malformed")
        else:
            path = (project_root / relative).resolve()
            try:
                path.relative_to(project_root.resolve())
            except ValueError:
                errors.append(f"visual package {key} escapes the output root")
                continue
            if not path.is_file():
                errors.append(f"visual package {key} file is missing")
            else:
                actual = _file_hash(path)
                if actual != asset_hash[7:]:
                    errors.append(f"visual package {key} asset hash does not match the file")
                try:
                    viewable = path.read_bytes().lstrip().startswith(b"<svg")
                except OSError:
                    viewable = False
                if not viewable:
                    errors.append(f"visual package {key} is not a viewable SVG")
        if asset_ref.get("media_type") != "image/svg+xml":
            errors.append(f"visual package {key} media type is not image/svg+xml")
        if asset_ref.get("version") != "1.0.0":
            errors.append(f"visual package {key} asset version is missing")
        provenance = item.get("provenance")
        if not isinstance(provenance, Mapping):
            errors.append(f"visual package {key} provenance is missing")
        else:
            source_commit = provenance.get("source_commit")
            if not isinstance(source_commit, str) or not SHA40.fullmatch(source_commit):
                errors.append(f"visual package {key} provenance source commit is missing")
            elif source_commit == "0" * 40 and not fixture_only:
                errors.append(f"visual package {key} provenance source commit is synthetic")
            source_repository = provenance.get("source_repository")
            if not isinstance(source_repository, str) or not source_repository.strip():
                errors.append(f"visual package {key} provenance source repository is missing")
            source_at_commit = provenance.get("source_repository_at_commit")
            if not isinstance(source_at_commit, str) or not source_at_commit.endswith(f"@{source_commit}"):
                errors.append(f"visual package {key} provenance source commit locator is missing")
            if not isinstance(provenance.get("evidence_locator"), str) or not provenance["evidence_locator"].strip():
                errors.append(f"visual package {key} evidence locator is missing")
        safety = item.get("safety")
        if not isinstance(safety, Mapping):
            errors.append(f"visual package {key} safety metadata is missing")
        else:
            if safety.get("rights_status") != "PROJECT_INTERNAL":
                errors.append(f"visual package {key} rights status is not explicit")
            expected_safety = "CLEAR" if key == "board" else "REVIEW_REQUIRED"
            if safety.get("safety_status") != expected_safety:
                errors.append(f"visual package {key} safety status is not explicit")
            if safety.get("external_validation_status") != "NOT_RUN":
                errors.append(f"visual package {key} external validation was not preserved")
            if safety.get("physical_validation_status") != "NOT_RUN":
                errors.append(f"visual package {key} physical validation was not preserved")

    if not markdown_path.is_file():
        errors.append("production plan markdown is missing")
    else:
        try:
            markdown = markdown_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append("production plan markdown cannot be read")
        else:
            for relative in (BOARD_RELATIVE_PATH, MOCKUP_RELATIVE_PATH):
                link = f"](visual-package/{Path(relative).name})"
                if link not in markdown and relative not in markdown:
                    errors.append(f"production plan markdown link is missing for {relative}")
    return errors


def project_visual_package(
    package: Mapping[str, Any],
    *,
    project_root: Path,
    production_commit: str,
    run_id: str,
    fixture_only: bool,
) -> dict[str, Any]:
    """Project child metadata into the parent evidence envelope."""

    errors = validate_visual_package_boundary(
        package,
        project_root=project_root,
        markdown_path=project_root / "03_plan/production-plan.md",
        production_commit=production_commit,
        run_id=run_id,
        fixture_only=fixture_only,
    )
    if errors:
        raise VisualPackageBoundaryError("; ".join(errors[:5]))
    result: dict[str, Any] = {
        "schema_version": str(package.get("schema_version")),
        "package_id": str(package.get("package_id")),
        "revision": package.get("revision"),
        "status": package.get("status"),
        "source_repository": "agentic-art-production",
        "source_commit": production_commit,
        "metadata_locator": f"run://{run_id}/production/visual-package.yaml",
        "package_hash": _digest(package),
        "fixture_only": fixture_only,
    }
    for key in ("board", "mockup"):
        item = package[key]
        asset = item["asset_ref"]
        provenance = item["provenance"]
        safety = item["safety"]
        result[key] = {
            "kind": item["kind"],
            "title": str(item.get("title", key)),
            "relative_path": item["relative_path"],
            "opaque_reference": f"run://{run_id}/production/{item['relative_path']}",
            "asset_version": asset["version"],
            "content_hash": asset["sha256"][7:],
            "media_type": asset["media_type"],
            "rights_status": safety["rights_status"],
            "safety_status": safety["safety_status"],
            "external_validation_status": safety["external_validation_status"],
            "physical_validation_status": safety["physical_validation_status"],
            "provenance_source_repository": provenance["source_repository"],
            "provenance_source_commit": provenance["source_commit"],
            "provenance_evidence_locator": provenance["evidence_locator"],
        }
    return result


def _fixture_svg(kind: str) -> bytes:
    label = html.escape("Visual reference board" if kind == "board" else "Conceptual mockup")
    accent = "#2563eb" if kind == "board" else "#7c3aed"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">'
        f'<rect width="640" height="360" fill="#f8fafc"/><rect x="40" y="40" width="560" height="280" fill="none" stroke="{accent}" stroke-width="4"/>'
        f'<text x="64" y="100" font-family="sans-serif" font-size="28" fill="#111827">{label}</text>'
        '<path d="M90 250 H550 M320 120 V280" stroke="#475569" stroke-width="6" fill="none"/>'
        '</svg>\n'
    ).encode("utf-8")


def build_fixture_visual_package(project_root: Path, *, production_commit: str, run_id: str) -> dict[str, Any]:
    """Materialize a deterministic, synthetic package only for the offline lane."""

    board = _fixture_svg("board")
    mockup = _fixture_svg("mockup")
    board_hash = _digest(board)
    mockup_hash = _digest(mockup)
    provenance = {
        "source_repository": "agentic-art-orchestration-fixture",
        "source_commit": "0" * 40,
        "source_repository_at_commit": "agentic-art-orchestration-fixture@" + "0" * 40,
        "evidence_locator": "fixture://purpose-e2e/visual-language",
        "generated_by_task_id": "PURPOSE-VISUAL-PACKAGE-001",
    }
    package: dict[str, Any] = {
        "schema_version": "1.0.0",
        "package_id": "VP001",
        "revision": 1,
        "status": "READY",
        "board": {
            "kind": "BOARD",
            "title": "Visual reference board · transparent boundary light",
            "relative_path": BOARD_RELATIVE_PATH,
            "asset_ref": {"asset_id": "AS001", "uri": "urn:asset:visual-package:VP001-board", "version": "1.0.0", "sha256": f"sha256:{board_hash}", "media_type": "image/svg+xml", "rights_status": "PROJECT_INTERNAL"},
            "provenance": provenance,
            "safety": {"rights_status": "PROJECT_INTERNAL", "safety_status": "CLEAR", "external_validation_status": "NOT_RUN", "physical_validation_status": "NOT_RUN", "safety_note": "Synthetic fixture only; no external material was used."},
        },
        "mockup": {
            "kind": "MOCKUP",
            "title": "Concept mockup · transparent boundary light",
            "relative_path": MOCKUP_RELATIVE_PATH,
            "asset_ref": {"asset_id": "AS002", "uri": "urn:asset:visual-package:VP001-mockup", "version": "1.0.0", "sha256": f"sha256:{mockup_hash}", "media_type": "image/svg+xml", "rights_status": "PROJECT_INTERNAL"},
            "provenance": provenance,
            "safety": {"rights_status": "PROJECT_INTERNAL", "safety_status": "REVIEW_REQUIRED", "external_validation_status": "NOT_RUN", "physical_validation_status": "NOT_RUN", "safety_note": "Conceptual/simulated only; physical and external validation remain human-gated."},
            "representation": "CONCEPTUAL",
            "dimensions": "Not to scale; physical dimensions are not supplied.",
            "materials": "Material selection remains provisional.",
            "placement": "Viewer follows the marked return path.",
            "physical_validation_note": "PHYSICAL_EXTERNAL validation: NOT_RUN.",
        },
        "source_refs": [{"source_ref_id": "fixture-visual-language", "locator": "fixture://purpose-e2e/visual-language", "derivation_evidence": "Synthetic fixture metadata.", "rights_status": "UNKNOWN", "adoption_status": "CITATION_ONLY", "rejection_reason": "No external asset body is adopted."}],
        "gaps": [],
        "determinism": {"algorithm": "visual-package-boundary-fixture-v1", "seed": "purpose-e2e-transparent-boundary-v1"},
    }
    package["integrity"] = {"content_sha256": _digest(package)}
    plan_dir = project_root / "03_plan"
    (project_root / "03_plan/visual-package").mkdir(parents=True, exist_ok=True)
    (project_root / BOARD_RELATIVE_PATH).write_bytes(board)
    (project_root / MOCKUP_RELATIVE_PATH).write_bytes(mockup)
    (plan_dir / "visual-package.yaml").write_text(yaml_dump(package), encoding="utf-8")
    return package


def yaml_dump(value: object) -> str:
    """Local YAML serializer kept behind the fixture-only helper."""
    import yaml

    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
