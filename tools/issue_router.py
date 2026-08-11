#!/usr/bin/env python3
"""Route privacy-minimal feedback to authoritative Issue candidates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
PARENT_REPOSITORY = "agentic-art-orchestration"
INFERRED_KINDS = {"inferred_friction", "inferred_need"}
EXPLICIT_KINDS = {"explicit_request", "explicit_dissatisfaction", "output_correction", "knowledge_gap"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")

try:
    from tools.validate import load_yaml, validate_feedback_signal, validate_issue_routing
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(ROOT))
    from tools.validate import load_yaml, validate_feedback_signal, validate_issue_routing


class IssueRouterError(ValueError):
    """Feedback cannot be routed safely."""


def _error(detail: str, remediation: str) -> IssueRouterError:
    return IssueRouterError(f"issue router: {detail}; remediation: {remediation}")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _timestamp(value: object) -> tuple[datetime, str]:
    if not isinstance(value, str):
        raise _error("feedback observed_at must be a string", "retain the source timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error(f"invalid feedback timestamp {value!r}", "use an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise _error("feedback timestamp must include timezone", "include Z or an explicit UTC offset")
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


def _expected_owner(summary_code: str) -> str | None:
    explicit = {
        "request:add-art-evidence": "art-history",
    }
    if summary_code in explicit:
        return explicit[summary_code]
    prefixes = (
        ("self-model:", "self-model"),
        ("self:", "self-model"),
        ("art-history:", "art-history"),
        ("art:", "art-history"),
        ("marketing-trends:", "marketing-trends"),
        ("marketing:", "marketing-trends"),
        ("research:", "agentic-art-research"),
        ("consumer:", "agentic-art-research"),
    )
    for prefix, owner in prefixes:
        if summary_code.startswith(prefix):
            return owner
    return PARENT_REPOSITORY if summary_code.startswith(
        ("friction:", "need:", "ux:", "retrieval:", "adapter:", "artifact:", "orchestration:")
    ) else None


def _role(owner: str, repositories: Mapping[str, dict]) -> str:
    return "PARENT" if owner == PARENT_REPOSITORY else "CHILD"


def _issue_key(summary_code: str, candidates: list[str]) -> str:
    return f"issue:{_hash({'summary_code': summary_code, 'candidates': sorted(candidates)})[:32]}"


def _privacy_summary(summary_code: str, owner: str | None) -> str:
    target = owner or "an unresolved authority"
    return f"Feedback summary code {summary_code} requires review by {target}; no raw feedback text is included."


def _acceptance(summary_code: str) -> list[str]:
    return [
        f"Review feedback summary code {summary_code} at the authoritative repository boundary.",
        "Preserve source artifact and evidence references; do not promote inferred feedback to user fact.",
    ]


def _candidate(
    feedback: Mapping[str, object],
    target: str | None,
    candidates: list[str],
    permitted: bool,
) -> dict:
    summary_code = feedback["summary_code"]
    return {
        "issue_key": _issue_key(summary_code, candidates),
        "target_repository": target,
        "summary_code": summary_code,
        "privacy_safe_summary": _privacy_summary(summary_code, target),
        "source_feedback_ids": [feedback["feedback_id"]],
        "acceptance": _acceptance(summary_code),
        "creation_permitted": permitted,
        "human_gate": True,
        "side_effect": "NONE",
    }


def _route_one(feedback: Mapping[str, object], repositories: Mapping[str, dict]) -> dict:
    feedback_id = feedback["feedback_id"]
    owner = feedback["target"]["owner_repository"]
    routing_status = feedback["target"]["routing_status"]
    summary_code = feedback["summary_code"]
    kind = feedback["kind"]
    confidence = feedback["confidence"]
    candidates = [owner]
    expected = _expected_owner(summary_code)
    if expected is not None and expected != owner:
        candidates = sorted({owner, expected})
        resolved_owner = None
        target_role = "TRIAGE"
        status = "TRIAGE"
        reason = "summary code authority conflicts with the feedback target; retain both candidates for triage"
    else:
        resolved_owner = owner
        target_role = _role(owner, repositories)
        status = "ROUTED"
        reason = "confirmed manifest authority matches the feedback target"
        if routing_status != "confirmed":
            resolved_owner = None
            target_role = "TRIAGE"
            status = "TRIAGE"
            reason = "target authority is a candidate or triage state, so routing requires review"
        elif kind in INFERRED_KINDS and (
            confidence.get("level") != "high" or confidence.get("score", 0) < 0.8
        ):
            resolved_owner = None
            target_role = "TRIAGE"
            status = "TRIAGE"
            reason = "inferred feedback confidence is below the automatic routing threshold"

    if owner != PARENT_REPOSITORY:
        profile = repositories.get(owner, {}).get("knowledge_profile", {})
        if profile.get("feedback_owner") != owner:
            resolved_owner = None
            target_role = "TRIAGE"
            status = "TRIAGE"
            reason = "manifest knowledge profile does not confirm the proposed child feedback owner"

    if feedback["consent"]["issue_creation_permitted"] is not True:
        return {
            "feedback_id": feedback_id,
            "kind": kind,
            "source": copy.deepcopy(feedback["source"]),
            "summary_code": summary_code,
            "evidence_refs": list(feedback["evidence_refs"]),
            "confidence": copy.deepcopy(confidence),
            "inference": {
                "is_inferred": kind in INFERRED_KINDS,
                "hypothesis_status": "unconfirmed" if kind in INFERRED_KINDS else "not-applicable",
            },
            "candidate_repositories": sorted(set(candidates)),
            "target_repository": owner,
            "target_role": _role(owner, repositories),
            "routing_status": "BLOCKED",
            "reason": "feedback consent does not permit Issue creation",
            "issue_candidate": None,
        }

    candidate = _candidate(feedback, resolved_owner, candidates, status == "ROUTED")
    return {
        "feedback_id": feedback_id,
        "kind": kind,
        "source": copy.deepcopy(feedback["source"]),
        "summary_code": summary_code,
        "evidence_refs": list(feedback["evidence_refs"]),
        "confidence": copy.deepcopy(confidence),
        "inference": {
            "is_inferred": kind in INFERRED_KINDS,
            "hypothesis_status": "unconfirmed" if kind in INFERRED_KINDS else "not-applicable",
        },
        "candidate_repositories": sorted(set(candidates)),
        "target_repository": resolved_owner,
        "target_role": target_role,
        "routing_status": status,
        "reason": reason,
        "issue_candidate": candidate,
    }


def route_feedback(
    feedback_signals: list[Mapping[str, object]],
    manifest: Mapping[str, object] | None = None,
    routing_run_id: str = "ISSUE-ROUTER-001:attempt-1",
) -> dict:
    """Route validated feedback without creating or updating a remote Issue."""
    if not isinstance(feedback_signals, list) or not feedback_signals:
        raise _error("feedback_signals must be a non-empty list", "provide at least one feedback envelope")
    if not isinstance(routing_run_id, str) or not routing_run_id or ID_PATTERN.fullmatch(routing_run_id) is None:
        raise _error("routing_run_id is invalid", "reuse a stable routing execution ID")
    repositories = _manifest_index(manifest or load_yaml(ROOT / "config/repositories.yaml"))
    prepared: list[dict] = []
    seen_feedback_ids: set[str] = set()
    observed_times: list[datetime] = []
    for index, feedback in enumerate(feedback_signals):
        if not isinstance(feedback, Mapping):
            raise _error(f"feedback_signals[{index}] must be an object", "pass feedback-signal/v1 metadata")
        errors = validate_feedback_signal(dict(feedback), f"issue-router feedback[{index}]")
        if errors:
            raise IssueRouterError("\n".join(errors))
        feedback_id = feedback["feedback_id"]
        if feedback_id in seen_feedback_ids:
            raise _error(f"duplicate feedback_id {feedback_id!r}", "retain one input signal per stable feedback ID")
        seen_feedback_ids.add(feedback_id)
        observed, _ = _timestamp(feedback["observed_at"])
        observed_times.append(observed)
        prepared.append(copy.deepcopy(dict(feedback)))

    routes = [_route_one(feedback, repositories) for feedback in sorted(prepared, key=lambda item: item["feedback_id"])]
    canonical_by_key: dict[str, dict] = {}
    suppressions: list[dict] = []
    for route in routes:
        candidate = route["issue_candidate"]
        if candidate is None:
            continue
        key = candidate["issue_key"]
        canonical = canonical_by_key.get(key)
        if canonical is None:
            canonical_by_key[key] = route
            continue
        canonical_candidate = canonical["issue_candidate"]
        canonical_candidate["source_feedback_ids"].append(route["feedback_id"])
        canonical_candidate["source_feedback_ids"] = sorted(set(canonical_candidate["source_feedback_ids"]))
        route["routing_status"] = "DUPLICATE_SUPPRESSED"
        route["reason"] = "same summary code and authority already has a canonical Issue candidate"
        route["target_repository"] = canonical["target_repository"]
        route["target_role"] = canonical["target_role"]
        route["issue_candidate"] = None
        suppressions.append(
            {
                "issue_key": key,
                "canonical_feedback_id": canonical["feedback_id"],
                "suppressed_feedback_id": route["feedback_id"],
            }
        )

    generated_at = max(observed_times).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    result = {
        "contract_version": "issue-routing/v1",
        "routing_run_id": routing_run_id,
        "lane": "FEEDBACK_ROUTING",
        "generated_at": generated_at,
        "interaction_blocking": False,
        "user_artifact_policy": "READ_ONLY",
        "input_feedback_ids": sorted(seen_feedback_ids),
        "routes": routes,
        "duplicate_suppressions": sorted(suppressions, key=lambda item: (item["issue_key"], item["suppressed_feedback_id"])),
        "issue_operations": [],
    }
    errors = validate_issue_routing(result, "issue-router result")
    if errors:
        raise IssueRouterError("\n".join(errors))
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
    parser = argparse.ArgumentParser(description="Route metadata-only feedback to authoritative Issue candidates")
    parser.add_argument("--feedback", action="append", type=Path, default=[], help="feedback-signal/v1 JSON file; repeat for multiple signals")
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/repositories.yaml")
    parser.add_argument("--routing-run-id", default="ISSUE-ROUTER-001:attempt-1")
    parser.add_argument("--output", type=Path, default=ROOT / "data/feedback-routing.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        paths = args.feedback or [
            ROOT / "tests/fixtures/feedback/valid_explicit.json",
            ROOT / "tests/fixtures/feedback/valid_inferred.json",
        ]
        feedback: list[dict] = []
        for path in paths:
            with path.open(encoding="utf-8") as handle:
                feedback.append(json.load(handle))
        manifest = load_yaml(args.manifest)
        result = route_feedback(feedback, manifest, args.routing_run_id)
        content = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        output_path = args.output.resolve()
        if args.check:
            if not output_path.is_file():
                raise _error("routing output is missing", "run without --check to materialize feedback-routing.json")
            if output_path.read_text(encoding="utf-8") != content:
                raise _error("routing output is stale", "rerun the router without --check")
        else:
            _write_atomic(output_path, content)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "command": "issue-router",
                "changed": not args.check,
                "route_count": len(result["routes"]),
                "duplicate_suppression_count": len(result["duplicate_suppressions"]),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
