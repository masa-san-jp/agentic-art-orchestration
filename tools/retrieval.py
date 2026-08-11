#!/usr/bin/env python3
"""Route structured conversational retrieval requests to immutable repository evidence."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from itertools import combinations
from typing import Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")

try:
    from tools.validate import (
        load_yaml,
        validate_retrieval_index,
        validate_retrieval_request,
        validate_retrieval_result,
    )
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(ROOT))
    from tools.validate import (
        load_yaml,
        validate_retrieval_index,
        validate_retrieval_request,
        validate_retrieval_result,
    )


class RetrievalError(ValueError):
    """Retrieval cannot safely interpret the request or index."""


def _error(detail: str, remediation: str) -> RetrievalError:
    return RetrievalError(f"retrieval: {detail}; remediation: {remediation}")


def _timestamp(value: object) -> tuple[datetime, str]:
    if not isinstance(value, str):
        raise _error("observed_at must be a string", "use an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error(f"invalid observed_at {value!r}", "repair the structured request timestamp") from exc
    if parsed.tzinfo is None:
        raise _error("observed_at must include timezone", "include Z or an explicit UTC offset")
    normalized = parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return parsed, normalized


def _manifest_index(manifest: Mapping[str, object]) -> dict[str, dict]:
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list):
        raise _error("manifest.repositories must be a list", "load config/repositories.yaml")
    result: dict[str, dict] = {}
    for repository in repositories:
        if not isinstance(repository, dict) or not isinstance(repository.get("id"), str):
            raise _error("manifest repository lacks an ID", "repair config/repositories.yaml")
        result[repository["id"]] = repository
    return result


def _load_inputs(
    request: Mapping[str, object],
    index: Mapping[str, object],
    manifest: Mapping[str, object],
) -> tuple[dict, dict, dict[str, dict]]:
    request_copy = deepcopy(dict(request))
    index_copy = deepcopy(dict(index))
    manifest_copy = deepcopy(dict(manifest))
    request_errors = validate_retrieval_request(request_copy, "retrieval request", manifest_copy)
    if request_errors:
        raise RetrievalError("\n".join(request_errors))
    index_errors = validate_retrieval_index(index_copy, manifest_copy, "retrieval index")
    if index_errors:
        raise RetrievalError("\n".join(index_errors))
    return request_copy, index_copy, _manifest_index(manifest_copy)


def _freshness_allowed(status: str, preference: str) -> bool:
    if preference == "current-only":
        return status == "current"
    if preference == "current-or-unknown":
        return status in {"current", "unknown"}
    return True


def _select_minimum_repositories(
    candidate_capabilities: Mapping[str, set[str]],
    requested: set[str],
) -> tuple[list[str], set[str]]:
    candidates = sorted(candidate_capabilities)
    if not candidates:
        return [], set()

    full_cover: tuple[str, ...] | None = None
    for size in range(1, len(candidates) + 1):
        for combination in combinations(candidates, size):
            coverage = set().union(*(candidate_capabilities[repository] for repository in combination))
            if requested.issubset(coverage):
                full_cover = combination
                break
        if full_cover is not None:
            break

    if full_cover is None:
        partial_options: list[tuple[int, int, tuple[str, ...], set[str]]] = []
        for size in range(1, len(candidates) + 1):
            for combination in combinations(candidates, size):
                coverage = set().union(*(candidate_capabilities[repository] for repository in combination))
                partial_options.append((-len(coverage & requested), size, combination, coverage & requested))
        _, _, selected, coverage = min(partial_options)
        return list(selected), coverage

    selected_coverage = set().union(*(candidate_capabilities[repository] for repository in full_cover)) & requested
    return list(full_cover), selected_coverage


def route_query(
    request: Mapping[str, object],
    index: Mapping[str, object],
    manifest: Mapping[str, object] | None = None,
    retrieval_run_id: str = "RETRIEVAL-001:attempt-1",
) -> dict:
    """Return deterministic evidence metadata without storing the raw conversational query."""
    if not isinstance(retrieval_run_id, str) or not retrieval_run_id or ID_PATTERN.fullmatch(retrieval_run_id) is None:
        raise _error("retrieval_run_id is invalid", "reuse a stable retrieval execution ID")
    loaded_manifest = deepcopy(dict(manifest)) if manifest is not None else load_yaml(ROOT / "config/repositories.yaml")
    request_copy, index_copy, repositories = _load_inputs(request, index, loaded_manifest)
    _, generated_at = _timestamp(request_copy["observed_at"])
    requested_codes = set(request_copy["capability_codes"])
    preference = request_copy["freshness_preference"]
    preferred = set(request_copy.get("preferred_repositories", []))

    entries_by_repository: dict[str, list[dict]] = {}
    candidate_capabilities: dict[str, set[str]] = {}
    for entry in index_copy["entries"]:
        repository_id = entry["repository"]
        if preferred and repository_id not in preferred:
            continue
        if not _freshness_allowed(entry["freshness_status"], preference):
            continue
        matched = set(entry["capability_codes"]) & requested_codes
        if not matched:
            continue
        entries_by_repository.setdefault(repository_id, []).append(entry)
        candidate_capabilities.setdefault(repository_id, set()).update(matched)

    selected_ids, covered_codes = _select_minimum_repositories(candidate_capabilities, requested_codes)
    selected_ids = sorted(selected_ids)
    selected_set = set(selected_ids)
    selected_repositories: list[dict] = []
    evidence: list[dict] = []
    unknowns: set[str] = set()
    domain_constraints: set[str] = set()

    for repository_id in selected_ids:
        repository = repositories[repository_id]
        profile = repository["knowledge_profile"]
        matched_codes = sorted(candidate_capabilities[repository_id] & requested_codes)
        selected_repositories.append(
            {
                "repository": repository_id,
                "role": repository["role"],
                "authority": repository["authority"],
                "source_commit": repository["observed_commit"],
                "matched_capability_codes": matched_codes,
                "selection_reason": "minimum relevant set covers capability codes: " + ", ".join(matched_codes),
                "evidence_policy": {
                    "minimum_quality": profile["evidence_rules"]["minimum_quality"],
                    "requires_locator": profile["evidence_rules"]["requires_locator"],
                },
                "freshness_policy": {
                    "policy": profile["freshness_rules"]["policy"],
                    "revalidation_required": profile["freshness_rules"]["revalidation_required"],
                },
            }
        )
        domain_constraints.add(f"repository-authority:{repository_id}")
        domain_constraints.add(
            f"minimum-evidence-quality:{repository_id}:{profile['evidence_rules']['minimum_quality']}"
        )
        domain_constraints.add(
            f"freshness-policy:{repository_id}:{profile['freshness_rules']['policy']}"
        )
        for entry in sorted(entries_by_repository[repository_id], key=lambda item: item["evidence_id"]):
            matched = sorted(set(entry["capability_codes"]) & requested_codes)
            evidence.append(
                {
                    "evidence_id": entry["evidence_id"],
                    "repository": repository_id,
                    "source_commit": entry["source_commit"],
                    "locator": entry["locator"],
                    "evidence_kind": entry["evidence_kind"],
                    "freshness_status": entry["freshness_status"],
                    "matched_capability_codes": matched,
                    "unknowns": list(entry["unknowns"]),
                    "domain_constraints": list(entry["domain_constraints"]),
                }
            )
            unknowns.update(entry["unknowns"])
            domain_constraints.update(entry["domain_constraints"])
            if entry["freshness_status"] in {"stale", "unknown"} and profile["freshness_rules"]["revalidation_required"]:
                unknowns.add(f"freshness-revalidation-required:{repository_id}")

    uncovered = sorted(requested_codes - covered_codes)
    unknowns.update(f"capability-unmatched:{code}" for code in uncovered)
    status = "NO_MATCH" if not selected_ids else ("COMPLETE_WITH_GAPS" if uncovered or unknowns else "COMPLETE")
    result = {
        "contract_version": "retrieval-result/v1",
        "retrieval_run_id": retrieval_run_id,
        "lane": "FRONTSTAGE_RETRIEVAL",
        "generated_at": generated_at,
        "interaction_blocking": False,
        "user_artifact_policy": "READ_ONLY",
        "request_ref": request_copy["request_id"],
        "intent_code": request_copy["intent_code"],
        "capability_codes": list(request_copy["capability_codes"]),
        "status": status,
        "selected_repositories": selected_repositories,
        "evidence": evidence,
        "unknowns": sorted(unknowns),
        "domain_constraints": sorted(domain_constraints),
        "privacy": {
            "consent_scope": request_copy["privacy"]["consent_scope"],
            "retention": "reference-only",
            "raw_query_stored": False,
            "direct_identifiers_stored": False,
        },
        "retrieval_operations": [],
    }
    result_errors = validate_retrieval_result(result, loaded_manifest, request_copy, "retrieval result")
    if result_errors:
        raise RetrievalError("\n".join(result_errors))
    return result


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Route structured retrieval to minimum relevant repository evidence")
    parser.add_argument("--request", type=Path, default=ROOT / "tests/fixtures/retrieval/valid_art.json")
    parser.add_argument("--index", type=Path, default=ROOT / "tests/fixtures/retrieval/index.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/repositories.yaml")
    parser.add_argument("--retrieval-run-id", default="RETRIEVAL-001:attempt-1")
    parser.add_argument("--output", type=Path, default=ROOT / "data/retrieval-result.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        with args.request.open(encoding="utf-8") as handle:
            request = json.load(handle)
        with args.index.open(encoding="utf-8") as handle:
            index = json.load(handle)
        manifest = load_yaml(args.manifest)
        result = route_query(request, index, manifest, args.retrieval_run_id)
        content = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        output_path = args.output.resolve()
        if args.check:
            if not output_path.is_file():
                raise _error("retrieval output is missing", "run without --check to materialize retrieval-result.json")
            if output_path.read_text(encoding="utf-8") != content:
                raise _error("retrieval output is stale", "rerun retrieval without --check")
        else:
            _write_atomic(output_path, content)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "command": "retrieval",
                "changed": not args.check,
                "status": result["status"],
                "selected_repository_count": len(result["selected_repositories"]),
                "evidence_count": len(result["evidence"]),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
