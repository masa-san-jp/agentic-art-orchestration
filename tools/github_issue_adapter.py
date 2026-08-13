#!/usr/bin/env python3
"""Deliver privacy-safe Issue candidates through create-only GitHub operations."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.issue_router import route_feedback  # noqa: E402
from tools.security import scan_payload  # noqa: E402
from tools.validate import _schema_errors, load_json, load_yaml, validate_issue_delivery_contract  # noqa: E402


POLICY_PATH = ROOT / "config/issue-delivery-policy.yaml"
SCHEMA_PATH = ROOT / "schemas/github-issue-delivery.schema.json"
MANIFEST_PATH = ROOT / "config/repositories.yaml"
DEFAULT_OUTPUT = ROOT / "data/github-issue-delivery.json"
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
FULL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ISSUE_URL_PATTERN = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)$")
EPOCH = "1970-01-01T00:00:00Z"
FORBIDDEN_KEYS = {
    "conversation", "transcript", "prompt", "message", "raw_text", "raw_conversation",
    "user_text", "assistant_text", "body", "content", "credential", "direct_identifier",
    "PRIVATE_RAW", "RESTRICTED",
}
SOURCE_KINDS = {"explicit", "inferred", "audit", "repository-update"}


class IssueDeliveryError(ValueError):
    """Issue delivery cannot continue inside the create-only boundary."""


class IssueProvider(Protocol):
    def search(self, repository: str, deduplication_key: str) -> list[dict]: ...

    def create(self, repository: str, title: str, body: str) -> dict: ...


def _error(detail: str, remediation: str) -> IssueDeliveryError:
    return IssueDeliveryError(f"issue delivery: {detail}; remediation: {remediation}")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable(value: object) -> str:
    return _hash(value)[:32]


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        return EPOCH
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return EPOCH
    if parsed.tzinfo is None:
        return EPOCH
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scan_forbidden(value: object, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in {item.lower() for item in FORBIDDEN_KEYS}:
                raise _error(f"candidate contains forbidden field at {path}.{key}", "pass metadata-only feedback or audit candidates")
            _scan_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_forbidden(child, f"{path}[{index}]")


def _policy_index(policy: Mapping[str, object]) -> dict[str, str]:
    entries = policy.get("allowlisted_repositories")
    if not isinstance(entries, list) or not entries:
        raise _error("Issue repository allowlist is missing", "declare explicit repository IDs and full names")
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise _error("Issue repository allowlist entry is invalid", "use an ID, full_name, and role")
        repository_id = entry.get("id")
        full_name = entry.get("full_name")
        if not isinstance(repository_id, str) or not ID_PATTERN.fullmatch(repository_id):
            raise _error("Issue allowlist ID is invalid", "use a stable repository ID")
        if not isinstance(full_name, str) or not FULL_NAME_PATTERN.fullmatch(full_name):
            raise _error("Issue allowlist full_name is invalid", "use owner/repository without a URL")
        role = entry.get("role")
        if role not in {"parent", "child"}:
            raise _error("Issue allowlist role is invalid", "declare parent or child authority explicitly")
        if repository_id in result and result[repository_id] != full_name:
            raise _error(f"Issue allowlist has conflicting entry for {repository_id}", "retain one authoritative full_name")
        result[repository_id] = full_name
    return result


def _allowlisted_repositories(manifest: Mapping[str, object], policy: Mapping[str, object]) -> dict[str, str]:
    policy_index = _policy_index(policy)
    manifest_index = {
        entry.get("id"): entry.get("full_name")
        for entry in manifest.get("repositories", [])
        if isinstance(entry, Mapping)
    }
    parent = policy.get("parent_repository")
    if not isinstance(parent, str) or parent not in policy_index:
        raise _error("parent repository is not allowlisted", "allowlist the authoritative orchestration repository")
    if policy_index[parent] != "masa-san-jp/agentic-art-orchestration":
        raise _error("parent repository full_name is not authoritative", "use masa-san-jp/agentic-art-orchestration as the parent target")
    for repository_id, full_name in policy_index.items():
        if repository_id != parent and manifest_index.get(repository_id) != full_name:
            raise _error(
                f"Issue allowlist does not match manifest for {repository_id}",
                "review the repository authority before enabling delivery",
            )
    return policy_index


class GithubApiProvider:
    """Minimal GitHub provider; response bodies are reduced to opaque metadata."""

    def __init__(self, token: str):
        if not token:
            raise _error("live mode requires a GitHub token", "set GITHUB_TOKEN or GH_TOKEN and retry with --confirm-live")
        self.token = token

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            "https://api.github.com" + path,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "agentic-art-orchestration-issue-delivery",
                **({"Content-Type": "application/json"} if body else {}),
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            detail = getattr(exc, "code", None) or type(exc).__name__
            raise _error(f"GitHub {method} request failed ({detail})", "inspect access without retrying a mutation blindly") from exc
        if not isinstance(value, dict):
            raise _error("GitHub returned an unexpected response", "inspect the provider contract before retrying")
        return value

    def get_repository(self, repository: str) -> dict:
        """Return only the repository preflight fields needed by the sandbox lane."""
        value = self._request("GET", f"/repos/{quote(repository, safe='/')}")
        permissions = value.get("permissions") if isinstance(value.get("permissions"), Mapping) else {}
        return {
            "full_name": value.get("full_name"),
            "archived": value.get("archived"),
            "has_issues": value.get("has_issues"),
            "push_permission": permissions.get("push") is True,
        }

    def search(self, repository: str, deduplication_key: str) -> list[dict]:
        query = urlencode({"q": f'repo:{repository} is:issue "{deduplication_key}"', "per_page": "10"})
        result = self._request("GET", f"/search/issues?{query}")
        items = result.get("items", [])
        return sorted(
            [
                {"number": item.get("number"), "url": item.get("html_url")}
                for item in items
                if isinstance(item, Mapping) and isinstance(item.get("number"), int) and isinstance(item.get("html_url"), str)
            ],
            key=lambda item: item["number"],
        )

    def create(self, repository: str, title: str, body: str) -> dict:
        result = self._request("POST", f"/repos/{quote(repository, safe='/')}/issues", {"title": title, "body": body})
        number = result.get("number")
        url = result.get("html_url")
        if not isinstance(number, int) or not isinstance(url, str):
            raise _error("GitHub create response lacks an Issue reference", "verify the provider response without writing again")
        return {"number": number, "url": url}


class FixtureProvider:
    """Networkless provider used to prove READ/CREATE/REUSE semantics."""

    def __init__(self, existing: Mapping[str, list[dict]] | None = None):
        self.existing = {key: list(value) for key, value in (existing or {}).items()}
        self.created: list[dict] = []

    def search(self, repository: str, deduplication_key: str) -> list[dict]:
        return list(self.existing.get(f"{repository}:{deduplication_key}", []))

    def create(self, repository: str, title: str, body: str) -> dict:
        number = int(_hash({"repository": repository, "title": title, "body": body})[:8], 16) % 1000000 + 1
        result = {"number": number, "url": f"https://github.com/{repository}/issues/{number}"}
        self.created.append({"repository": repository, "title": title, "body": body, "body_hash": _hash(body)})
        key = f"{repository}:{_extract_deduplication_key(body)}"
        self.existing.setdefault(key, []).append(result)
        return result


def _manifest_candidates(manifest: Mapping[str, object], policy: Mapping[str, object]) -> dict[str, str]:
    return _allowlisted_repositories(manifest, policy)


def _normalise_candidate(raw: Mapping[str, object], allowlist: Mapping[str, str]) -> dict:
    if not isinstance(raw, Mapping):
        raise _error("candidate is not an object", "pass a metadata-only Issue candidate")
    _scan_forbidden(dict(raw))
    target_id = raw.get("target_repository")
    target_full_name = allowlist.get(str(target_id))
    if target_full_name is None:
        raise _error(f"candidate target {target_id!r} is not allowlisted", "route only to an allowlisted repository")
    source_kind = raw.get("source_kind", "explicit")
    if source_kind == "feedback":
        source_kind = "inferred" if isinstance(raw.get("inference"), Mapping) and raw["inference"].get("is_inferred") is True else "explicit"
    if not isinstance(source_kind, str) or source_kind not in SOURCE_KINDS:
        raise _error("candidate source_kind is not supported", "use explicit, inferred, audit, or repository-update")
    deduplication_key = raw.get("deduplication_key") or raw.get("issue_key")
    finding_code = raw.get("finding_code")
    summary_code = raw.get("summary_code") or finding_code
    if not isinstance(deduplication_key, str) or not ID_PATTERN.fullmatch(deduplication_key):
        raise _error("candidate deduplication key is invalid", "use a stable opaque key")
    if not isinstance(summary_code, str) or not ID_PATTERN.fullmatch(summary_code):
        raise _error("candidate summary code is invalid", "use a stable summary code")
    summary = raw.get("privacy_safe_summary")
    if not isinstance(summary, str) or not summary or len(summary) > 500 or any(ord(char) < 32 and char not in "\t" for char in summary):
        raise _error("candidate privacy-safe summary is invalid", "retain a short metadata-only summary")
    acceptance = raw.get("acceptance") or [f"Review {summary_code} at the authoritative repository boundary."]
    if not isinstance(acceptance, list) or not acceptance or any(not isinstance(item, str) or not item or len(item) > 300 or any(ord(char) < 32 and char not in "\t" for char in item) for item in acceptance):
        raise _error("candidate acceptance is invalid", "retain short metadata-only acceptance criteria")
    if scan_payload(summary) or any(scan_payload(item) for item in acceptance):
        raise _error("candidate crosses the security boundary", "remove credential-like values from summary and acceptance")
    source_refs = raw.get("source_feedback_ids") or raw.get("source_refs") or [raw.get("candidate_id")]
    if not isinstance(source_refs, list) or not source_refs or any(not isinstance(item, str) or not ID_PATTERN.fullmatch(item) for item in source_refs):
        raise _error("candidate source references are invalid", "use opaque stable IDs only")
    inference = raw.get("inference") if isinstance(raw.get("inference"), Mapping) else {}
    is_inferred = source_kind == "inferred" or inference.get("is_inferred") is True
    if is_inferred:
        source_kind = "inferred"
    hypothesis_status = raw.get("inference_status") or inference.get("hypothesis_status") or inference.get("confirmation_status")
    if is_inferred and hypothesis_status != "unconfirmed":
        raise _error("inferred candidate is not explicitly unconfirmed", "retain the hypothesis boundary in the Issue")
    if not is_inferred:
        hypothesis_status = "not-applicable"
    if raw.get("creation_permitted") is not True or raw.get("human_gate") is not True:
        raise _error("candidate is not eligible for create-only delivery", "retain consent and human gate")
    if raw.get("side_effect") not in (None, "NONE"):
        raise _error("candidate declares a side effect", "Issue delivery must remain human-gated and create-only")
    candidate_id = raw.get("candidate_id") or f"candidate:{_stable(raw)}"
    if not isinstance(candidate_id, str) or not ID_PATTERN.fullmatch(candidate_id):
        candidate_id = f"candidate:{_stable({'candidate_id': candidate_id})}"
    confidence = raw.get("confidence")
    if isinstance(confidence, Mapping):
        confidence_value = confidence.get("level") or confidence.get("score") or "not-provided"
    elif isinstance(confidence, (str, int, float)) and not isinstance(confidence, bool):
        confidence_value = confidence
    else:
        confidence_value = "not-provided"
    if isinstance(confidence_value, str):
        if confidence_value not in {"low", "medium", "high", "explicit", "not-provided"}:
            raise _error("candidate confidence is not a recognized level", "use low, medium, high, explicit, or not-provided")
    elif isinstance(confidence_value, (int, float)) and not isinstance(confidence_value, bool):
        if not 0 <= confidence_value <= 1:
            raise _error("candidate confidence score is outside 0..1", "retain a normalized confidence score")
    else:
        raise _error("candidate confidence is invalid", "use an opaque confidence level or a score from 0 to 1")
    contradiction_refs = raw.get("contradiction_refs") or raw.get("counterevidence_refs") or []
    if not isinstance(contradiction_refs, list) or any(not isinstance(item, str) or not ID_PATTERN.fullmatch(item) for item in contradiction_refs):
        contradiction_refs = []
    return {
        "candidate_id": candidate_id,
        "source_kind": source_kind,
        "target_repository": str(target_id),
        "target_full_name": target_full_name,
        "deduplication_key": deduplication_key,
        "source_refs": sorted(set(source_refs)),
        "privacy_safe_summary": summary,
        "acceptance": list(dict.fromkeys(acceptance)),
        "inference": {"is_inferred": bool(is_inferred), "hypothesis_status": hypothesis_status},
        "summary_code": summary_code,
        "confidence": confidence_value,
        "contradiction_refs": sorted(set(contradiction_refs)),
    }


def _title(candidate: Mapping[str, object]) -> str:
    return f"[orchestration:{candidate['deduplication_key']}] {candidate['summary_code']}"


def _extract_deduplication_key(body: str) -> str:
    marker = re.search(r"orchestration-deduplication-key:\s*([A-Za-z0-9][A-Za-z0-9._:-]*)", body)
    return marker.group(1) if marker else f"unknown:{_stable(body)}"


def _body(candidate: Mapping[str, object], run_id: str, agent_id: str = "github-issue-adapter") -> str:
    lines = [
        f"<!-- orchestration-deduplication-key: {candidate['deduplication_key']} -->",
        "## Metadata-only feedback",
        f"- Source kind: `{candidate['source_kind']}`",
        f"- Summary code: `{candidate['summary_code']}`",
        f"- Privacy-safe summary: {candidate['privacy_safe_summary']}",
        f"- Target authority: `{candidate['target_repository']}` (`{candidate['target_full_name']}`)",
        f"- Agent/run: `{agent_id}` / `{run_id}`",
        f"- Inference status: `{candidate['inference']['hypothesis_status']}`",
        f"- Confidence: `{candidate['confidence']}`",
        f"- Contradiction references: {', '.join(f'`{item}`' for item in candidate['contradiction_refs']) or '`none-recorded`'}",
        f"- Source references: {', '.join(f'`{item}`' for item in candidate['source_refs'])}",
        "- Prohibited data scan: `PASS` (metadata-only body)",
        "",
        "## Acceptance",
    ]
    lines.extend(f"- {item}" for item in candidate["acceptance"])
    lines.append("\nThis Issue is create-only. Implementation, branch, commit, pull request, merge, release, and existing Issue mutation are not authorized.")
    body = "\n".join(lines)
    if scan_payload(body):
        raise _error("generated Issue body crosses the security boundary", "remove sensitive or credential-like content")
    return body


def _issue_ref(repository: str, value: Mapping[str, object]) -> tuple[int, str, str]:
    number = value.get("number")
    url = value.get("url")
    if not isinstance(number, int) or number < 1 or not isinstance(url, str):
        raise _error("provider returned an invalid Issue reference", "do not retry a mutation until the response is understood")
    match = ISSUE_URL_PATTERN.fullmatch(url)
    if not match or match.group(1) != repository or int(match.group(2)) != number:
        raise _error("provider returned an Issue URL outside the target repository", "discard the response and inspect provider access")
    return number, url, _hash({"repository": repository, "number": number})


def _record(candidate: Mapping[str, object], *, status: str, operation: str, issue_number: int | None = None, issue_url: str | None = None, issue_id_hash: str | None = None, creation_permitted: bool | None = None) -> dict:
    return {
        "candidate_id": candidate["candidate_id"],
        "source_kind": candidate["source_kind"],
        "target_repository": candidate["target_repository"],
        "target_full_name": candidate["target_full_name"],
        "deduplication_key": candidate["deduplication_key"],
        "source_refs": list(candidate["source_refs"]),
        "privacy_safe_summary": candidate["privacy_safe_summary"],
        "acceptance": list(candidate["acceptance"]),
        "inference": dict(candidate["inference"]),
        "creation_permitted": candidate.get("creation_permitted", True) if creation_permitted is None else creation_permitted,
        "human_gate": True,
        "status": status,
        "operation": operation,
        "issue_number": issue_number,
        "issue_url": issue_url,
        "issue_id_hash": issue_id_hash,
    }


def _blocked_record(raw: Mapping[str, object], reason: str, allowlist: Mapping[str, str]) -> dict:
    target_id = raw.get("target_repository") if isinstance(raw.get("target_repository"), str) else "agentic-art-orchestration"
    if target_id not in allowlist:
        target_id = "agentic-art-orchestration"
    candidate_id = raw.get("candidate_id") if isinstance(raw.get("candidate_id"), str) and ID_PATTERN.fullmatch(raw.get("candidate_id")) else f"candidate:{_stable(raw)}"
    key = raw.get("deduplication_key") or raw.get("issue_key")
    if not isinstance(key, str) or not ID_PATTERN.fullmatch(key):
        key = f"blocked:{_stable({'candidate_id': candidate_id, 'reason': reason})}"
    raw_source_kind = raw.get("source_kind")
    source_kind = raw_source_kind if isinstance(raw_source_kind, str) and raw_source_kind in SOURCE_KINDS else "audit"
    summary = "Candidate blocked before delivery; review the stable metadata and remediation."
    candidate = {
        "candidate_id": candidate_id,
        "source_kind": source_kind,
        "target_repository": target_id,
        "target_full_name": allowlist[target_id],
        "deduplication_key": key,
        "source_refs": [candidate_id],
        "privacy_safe_summary": summary,
        "acceptance": ["Resolve the delivery precondition at the authoritative repository boundary."],
        "inference": {"is_inferred": source_kind == "inferred", "hypothesis_status": "unconfirmed" if source_kind == "inferred" else "not-applicable"},
    }
    return _record(candidate, status="BLOCKED", operation="NONE", creation_permitted=False)


def deliver(candidates: list[Mapping[str, object]], manifest: Mapping[str, object], mode: str = "plan", provider: IssueProvider | None = None, run_id: str = "ISSUE-CREATE-001:attempt-1", policy: Mapping[str, object] | None = None) -> dict:
    if mode not in {"plan", "live"} or not ID_PATTERN.fullmatch(run_id):
        raise _error("mode or run_id is invalid", "use plan/live and a stable run ID")
    if not isinstance(candidates, list) or not candidates:
        raise _error("candidate list is empty", "supply at least one metadata-only Issue candidate")
    policy = policy or load_yaml(POLICY_PATH)
    policy_errors = validate_issue_delivery_contract(policy, load_json(SCHEMA_PATH), dict(manifest))
    if policy_errors:
        raise _error("delivery policy is invalid: " + "; ".join(policy_errors), "repair the allowlist and create-only contract before delivery")
    allowlist = _manifest_candidates(manifest, policy)
    normalized: dict[str, dict] = {}
    records: list[dict] = []
    for raw in candidates:
        try:
            candidate = _normalise_candidate(raw, allowlist)
        except IssueDeliveryError as exc:
            records.append(_blocked_record(raw if isinstance(raw, Mapping) else {}, str(exc), allowlist))
            continue
        key = candidate["deduplication_key"]
        existing = normalized.get(key)
        if existing is None:
            normalized[key] = candidate
        elif (existing["target_repository"], existing["summary_code"], existing["source_kind"]) != (candidate["target_repository"], candidate["summary_code"], candidate["source_kind"]):
            records.append(_record(candidate, status="BLOCKED", operation="NONE", creation_permitted=False))
        else:
            existing["source_refs"] = sorted(set(existing["source_refs"] + candidate["source_refs"]))

    remote_operations: list[dict] = []
    for key in sorted(normalized):
        candidate = normalized[key]
        if mode == "plan":
            records.append(_record(candidate, status="PLANNED", operation="NONE"))
            continue
        if provider is None:
            raise _error("live mode has no provider", "supply an authenticated provider")
        matches = provider.search(candidate["target_full_name"], key)
        remote_operations.append({"operation": "READ", "target_repository": candidate["target_repository"], "deduplication_key": key})
        if len(matches) > 1:
            records.append(_record(candidate, status="BLOCKED", operation="NONE", creation_permitted=False))
            continue
        if matches:
            number, url, issue_hash = _issue_ref(candidate["target_full_name"], matches[0])
            records.append(_record(candidate, status="REUSED", operation="REUSE", issue_number=number, issue_url=url, issue_id_hash=issue_hash))
            remote_operations.append({"operation": "REUSE", "target_repository": candidate["target_repository"], "deduplication_key": key, "issue_number": number})
        else:
            created = provider.create(candidate["target_full_name"], _title(candidate), _body(candidate, run_id))
            number, url, issue_hash = _issue_ref(candidate["target_full_name"], created)
            records.append(_record(candidate, status="CREATED", operation="CREATE", issue_number=number, issue_url=url, issue_id_hash=issue_hash))
            remote_operations.append({"operation": "CREATE", "target_repository": candidate["target_repository"], "deduplication_key": key, "issue_number": number})

    records.sort(key=lambda item: (item["deduplication_key"], item["candidate_id"], item["status"]))
    if any(record["status"] == "BLOCKED" for record in records) and not any(record["status"] in {"PLANNED", "CREATED", "REUSED"} for record in records):
        status = "BLOCKED"
    elif mode == "plan":
        status = "PARTIAL" if any(record["status"] == "BLOCKED" for record in records) else "PLANNED"
    else:
        live_statuses = {record["status"] for record in records if record["status"] in {"CREATED", "REUSED"}}
        status = "PARTIAL" if any(record["status"] == "BLOCKED" for record in records) or len(live_statuses) > 1 else (next(iter(live_statuses)) if live_statuses else "BLOCKED")
    result = {
        "contract_version": "github-issue-delivery/v1",
        "delivery_run_id": run_id,
        "mode": mode.upper(),
        "generated_at": EPOCH,
        "status": status,
        "records": records,
        "remote_operations": remote_operations,
    }
    errors = _schema_errors(result, load_json(SCHEMA_PATH))
    if errors:
        raise _error("delivery result violates its schema: " + "; ".join(errors), "repair the adapter contract before any live run")
    return result


def _fixture_candidates(manifest: Mapping[str, object]) -> list[dict]:
    routed = route_feedback(
        [
            load_json(ROOT / "tests/fixtures/feedback/valid_explicit.json"),
            load_json(ROOT / "tests/fixtures/feedback/valid_inferred.json"),
        ],
        manifest,
        "ISSUE-CREATE-001:fixture",
    )
    candidates = []
    for route in routed["routes"]:
        candidate = route.get("issue_candidate")
        if not isinstance(candidate, Mapping) or candidate.get("creation_permitted") is not True:
            continue
        candidate = dict(candidate)
        candidate["source_kind"] = "inferred" if route.get("kind") in {"inferred_friction", "inferred_need"} else "explicit"
        candidate["inference"] = {
            "is_inferred": candidate["source_kind"] == "inferred",
            "hypothesis_status": route.get("inference", {}).get("hypothesis_status", "not-applicable"),
        }
        candidate["confidence"] = route.get("confidence", {}).get("level", "not-provided")
        candidate["contradiction_refs"] = list(route.get("inference", {}).get("counterevidence_refs", []))
        candidates.append(candidate)
    return candidates


def _write_or_check(result: dict, output: Path, check: bool) -> None:
    content = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != content:
            raise _error("delivery output is missing or stale", "run without --check to materialize the deterministic plan")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deliver privacy-safe GitHub Issue candidates using create-only operations")
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--mode", choices=["plan", "live"])
    parser.add_argument("--plan", action="store_true", help="explicitly select networkless planning")
    parser.add_argument("--live", action="store_true", help="select live mode; --confirm-live is still required")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--candidate", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run-id", default="ISSUE-CREATE-001:attempt-1")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.plan and args.live:
            raise _error("--plan and --live cannot be combined", "select one delivery mode")
        if args.mode and (args.plan or args.live):
            raise _error("--mode cannot be combined with --plan or --live", "select one delivery mode")
        mode = args.mode or ("live" if args.live else "plan")
        manifest = load_yaml(MANIFEST_PATH)
        if mode == "live" and not args.confirm_live:
            raise _error("live mode requires --confirm-live", "keep plan mode unless live Issue creation is explicitly authorized")
        if args.fixture and args.candidate:
            raise _error("--fixture and --candidate cannot be combined", "choose one input source")
        candidates = _fixture_candidates(manifest) if args.fixture else [load_json(path) for path in args.candidate]
        if not candidates:
            raise _error("no Issue candidates were supplied", "provide --fixture or --candidate")
        provider = None
        if mode == "live":
            provider = GithubApiProvider(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "")
        result = deliver(candidates, manifest, mode, provider, args.run_id)
        _write_or_check(result, args.output.resolve(), args.check)
        print(json.dumps({"command": "github-issue-adapter", "changed": not args.check, "mode": mode, "record_count": len(result["records"]), "remote_operation_count": len(result["remote_operations"])}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
