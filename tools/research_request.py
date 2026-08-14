#!/usr/bin/env python3
"""Derive the child-owned research-request contract from a selected candidate."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    from tools.signal_bundle import validate_signal_bundle
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.signal_bundle import validate_signal_bundle


REQUEST_ID = re.compile(r"^RR[0-9]{3,}$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$")


def _error(source: str, detail: str, remediation: str) -> str:
    return f"{source}: {detail}; remediation: {remediation}"


def _git_commit(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    commit = result.stdout.strip()
    if result.returncode != 0 or not SHA40.fullmatch(commit):
        raise ValueError(_error("research-request", "parent HEAD is not immutable", "run from a clean parent Git checkout"))
    return commit


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(_error(str(path), "expected an object", "provide selection or signal-bundle JSON"))
    return value


def _selected_signals(selection: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    selected_ids = {
        ref.get("signal_id")
        for candidate in selection.get("selected_candidates", [])
        for refs in candidate.get("inputs", {}).values()
        for ref in refs
        if isinstance(ref, dict) and isinstance(ref.get("signal_id"), str)
    }
    signals = [signal for signal in bundle["records"] if signal.get("signal_id") in selected_ids]
    if not signals:
        raise ValueError(_error("research-request", "selection has no signal references", "select a passing candidate with preserved provenance"))
    return sorted(signals, key=lambda signal: signal["signal_id"])


def _references(signals: list[dict[str, Any]]) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    seen: set[str] = set()
    for signal in signals:
        source = signal["source"]
        values = [f"urn:orchestration:signal:{signal['signal_id']}"]
        values.extend(f"urn:orchestration:evidence:{signal['signal_id']}:{index}" for index, _ in enumerate(signal.get("evidence_refs", []), 1))
        for uri in values:
            if uri in seen:
                continue
            seen.add(uri)
            references.append({
                "label": f"{source['repository']} signal {signal['signal_id']}",
                "uri": uri,
                "rights_status": "APPROVED_REFERENCE",
            })
    return references


def validate_research_request(request: dict[str, Any], source: str = "research-request") -> list[str]:
    errors: list[str] = []
    required = {"schema_version", "request_id", "requested_at", "source", "project", "intent", "constraints", "references", "open_questions", "data_boundary"}
    errors.extend(_error(source, f"missing field {field!r}", "preserve the child-owned research-request contract") for field in sorted(required - set(request)))
    if request.get("schema_version") != "1.0.0":
        errors.append(_error(f"{source}.schema_version", "unsupported version", "use 1.0.0"))
    if not isinstance(request.get("request_id"), str) or not REQUEST_ID.fullmatch(request.get("request_id", "")):
        errors.append(_error(f"{source}.request_id", "must match RR###", "use a stable request ID"))
    if not isinstance(request.get("requested_at"), str) or not TIMESTAMP.fullmatch(request.get("requested_at", "")):
        errors.append(_error(f"{source}.requested_at", "must be RFC 3339", "provide a deterministic requested_at"))
    source_value = request.get("source")
    if not isinstance(source_value, dict) or source_value.get("kind") != "REPOSITORY" or not source_value.get("system"):
        errors.append(_error(f"{source}.source", "must identify the parent repository", "use kind REPOSITORY and a non-empty system"))
    project = request.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("slug"), str) or not SLUG.fullmatch(project.get("slug", "")) or not project.get("title"):
        errors.append(_error(f"{source}.project", "has invalid slug or title", "use a lowercase project slug and explicit title"))
    intent = request.get("intent")
    if not isinstance(intent, dict) or any(not isinstance(intent.get(field), str) or not intent[field] for field in ("purpose", "creative_question", "intended_use")):
        errors.append(_error(f"{source}.intent", "purpose, creative_question, and intended_use are required", "derive explicit research intent from the selected candidate"))
    constraints = request.get("constraints")
    if not isinstance(constraints, dict) or constraints.get("publication_scope") not in {"PROJECT_INTERNAL", "PUBLIC_CITABLE"} or not isinstance(constraints.get("prohibited_actions"), list):
        errors.append(_error(f"{source}.constraints", "is incomplete", "keep research constraints explicit and closed"))
    if not isinstance(request.get("references"), list) or not isinstance(request.get("open_questions"), list):
        errors.append(_error(f"{source}", "references and open_questions must be lists", "preserve source references and unknowns"))
    boundary = request.get("data_boundary")
    if boundary != {"classification": "PROJECT_INTERNAL", "raw_data_included": False}:
        errors.append(_error(f"{source}.data_boundary", "raw data boundary is not fail-closed", "set PROJECT_INTERNAL and raw_data_included false"))
    return errors


def build_research_request(
    selection: dict[str, Any],
    bundle: dict[str, Any],
    *,
    request_id: str,
    requested_at: str,
    project_slug: str,
    project_title: str | None = None,
    source_commit: str,
) -> dict[str, Any]:
    if not SHA40.fullmatch(source_commit):
        raise ValueError(_error("research-request.source.commit", "must be a 40-character lowercase SHA", "pin the parent source commit"))
    bundle_errors = validate_signal_bundle(bundle)
    if bundle_errors:
        raise ValueError("\n".join(bundle_errors))
    signals = _selected_signals(selection, bundle)
    candidate_ids = [str(candidate["candidate_id"]) for candidate in selection.get("selected_candidates", [])]
    request = {
        "schema_version": "1.0.0",
        "request_id": request_id,
        "requested_at": requested_at,
        "source": {
            "kind": "REPOSITORY",
            "system": "agentic-art-orchestration",
            "repository": "masa-san-jp/agentic-art-orchestration",
            "commit": source_commit,
            "artifact_uri": f"urn:orchestration:selection:{selection.get('candidate_space_hash', 'unknown')}",
            "session_id": None,
        },
        "project": {"slug": project_slug, "title": project_title or f"Research for {project_slug}", "creator_id": None},
        "intent": {
            "purpose": f"Investigate the selected research candidate(s): {', '.join(candidate_ids)}.",
            "creative_question": "What evidence is needed to evaluate the selected candidate without turning an inference into a fact?",
            "intended_use": "Research planning and evidence collection only; no production or publication is authorized.",
            "audience_experience": None,
            "medium_materials": [],
        },
        "constraints": {
            "deadline": None,
            "budget": None,
            "publication_scope": "PROJECT_INTERNAL",
            "allowed_source_scopes": ["approved-personal-derived", "external-knowledge", "public"],
            "prohibited_actions": ["publish", "submit", "send", "purchase", "contract", "delete"],
            "technical": ["Preserve source repository commits and evidence locators."],
            "physical": [],
            "rights": ["Use only references accepted at the child boundary."],
            "safety": ["Do not include source payloads; retain only approved reference metadata."],
        },
        "references": _references(signals),
        "open_questions": [
            f"Which claims in selected candidate {candidate_id} can be independently supported?"
            for candidate_id in candidate_ids
        ] or ["Which selected signal relationships survive independent research?"],
        "data_boundary": {"classification": "PROJECT_INTERNAL", "raw_data_included": False},
    }
    errors = validate_research_request(request)
    if errors:
        raise ValueError("\n".join(errors))
    return request


def write_request(path: Path, request: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(request, allow_unicode=True, sort_keys=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--requested-at", required=True)
    parser.add_argument("--project-slug", required=True)
    parser.add_argument("--project-title")
    parser.add_argument("--source-commit", help="parent commit; defaults to the current checkout HEAD")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        source_commit = args.source_commit or _git_commit(Path(__file__).resolve().parents[1])
        request = build_research_request(_load_json(args.selection), _load_json(args.bundle), request_id=args.request_id, requested_at=args.requested_at, project_slug=args.project_slug, project_title=args.project_title, source_commit=source_commit)
        write_request(args.output, request)
        print(json.dumps({"command": "research-request", "request_id": request["request_id"], "status": "PASSED"}, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
