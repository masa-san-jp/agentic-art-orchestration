#!/usr/bin/env python3
"""Run the separately approved GitHub sandbox Issue qualification lane."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Mapping, Protocol

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.github_issue_adapter import GithubApiProvider  # noqa: E402
from tools.validate import _schema_errors, load_json, load_yaml, validate_github_sandbox_live_contract  # noqa: E402


POLICY_PATH = ROOT / "config/github-sandbox-live-policy.yaml"
SCHEMA_PATH = ROOT / "schemas/github-sandbox-live-evidence.schema.json"
MANIFEST_PATH = ROOT / "config/repositories.yaml"
DEFAULT_OUTPUT = ROOT / "data/github-sandbox-live-evidence.json"
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
ATTEMPT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
FULL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ISSUE_URL_PATTERN = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)$")
DEDUP_MARKER_PATTERN = re.compile(r"^<!-- github-sandbox-idempotency-key: ([a-z0-9][a-z0-9._:-]*) -->$", re.MULTILINE)
EPOCH = "1970-01-01T00:00:00Z"


class GithubSandboxLiveError(ValueError):
    """A sandbox qualification request is invalid or crosses its boundary."""


class GithubSandboxProvider(Protocol):
    def get_repository(self, repository: str) -> Mapping[str, object]: ...

    def search(self, repository: str, deduplication_key: str) -> list[dict]: ...

    def create(self, repository: str, title: str, body: str) -> dict: ...


def _error(detail: str, remediation: str) -> GithubSandboxLiveError:
    return GithubSandboxLiveError(f"github sandbox live: {detail}; remediation: {remediation}")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_attempt_id(attempt_id: object) -> str:
    if not isinstance(attempt_id, str) or ATTEMPT_ID_PATTERN.fullmatch(attempt_id) is None:
        raise _error(
            "attempt ID is invalid",
            "use --attempt-id with lowercase [a-z0-9][a-z0-9._-]{0,63}",
        )
    return attempt_id


def _deduplication_key(policy: Mapping[str, object], attempt_id: str) -> str:
    prefix = policy.get("idempotency_key_prefix")
    if not isinstance(prefix, str):
        raise _error("idempotency key prefix is missing", "repair the sandbox policy before any external operation")
    return f"{prefix}:{attempt_id}"


def _extract_deduplication_key(body: str) -> str:
    match = DEDUP_MARKER_PATTERN.search(body)
    if match is None:
        raise _error("created Issue body lacks the deduplication marker", "do not retry an ambiguous CREATE response")
    return match.group(1)


def _run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"INITIAL-OPS-GITHUB-SANDBOX:{timestamp}"


def _production_repositories(manifest: Mapping[str, object]) -> set[str]:
    repositories = {
        item.get("full_name")
        for item in manifest.get("repositories", [])
        if isinstance(item, Mapping) and isinstance(item.get("full_name"), str)
    }
    repositories.add("masa-san-jp/agentic-art-orchestration")
    return repositories


def _repository_from_environment(policy: Mapping[str, object]) -> str:
    approved = policy["approved_repository"]
    env_name = approved["id_env_var"]
    repository = os.environ.get(env_name, "").strip()
    if not repository:
        raise _error(f"live mode requires {env_name}", "set only a dedicated sandbox owner/name outside Git")
    if FULL_NAME_PATTERN.fullmatch(repository) is None:
        raise _error("approved sandbox repository is not owner/name", "set a GitHub repository full name without a URL")
    return repository


def _issue_ref(repository: str, value: Mapping[str, object]) -> tuple[int, str, str]:
    number = value.get("number")
    url = value.get("url")
    if not isinstance(number, int) or number < 1 or not isinstance(url, str):
        raise _error("provider returned an invalid Issue reference", "do not retry after an ambiguous provider response")
    match = ISSUE_URL_PATTERN.fullmatch(url)
    if not match or match.group(1) != repository or int(match.group(2)) != number:
        raise _error("provider returned an Issue URL outside the sandbox", "discard the response and inspect provider access")
    return number, url, _hash({"repository": repository, "number": number})


def _body(repository: str, deduplication_key: str) -> str:
    return "\n".join(
        [
            f"<!-- github-sandbox-idempotency-key: {deduplication_key} -->",
            "## Initial operations sandbox qualification",
            f"- Repository authority: `{repository}`",
            "- Scope: one metadata-only Issue create and idempotent reuse check.",
            "- Prohibited: update, close, delete, comment, label, branch, commit, pull request, merge, and release.",
            "- This Issue is a disposable qualification artifact; no production content is included.",
        ]
    )


def _remote(
    operation: str,
    repository: str,
    deduplication_key: str,
    issue_number: int | None = None,
    attempt: int | None = None,
) -> dict:
    result = {
        "operation": operation,
        "repository_id_hash": _hash(repository),
        "idempotency_key_hash": _hash_text(deduplication_key),
    }
    if issue_number is not None:
        result["issue_number"] = issue_number
    if attempt is not None:
        result["attempt"] = attempt
    return result


def _result(
    *,
    run_id: str,
    mode: str,
    status: str,
    operation: str,
    repository: str,
    deduplication_key: str,
    issue_id_hash: str | None,
    remote_operations: list[dict],
) -> dict:
    result = {
        "contract_version": "github-sandbox-live/v1",
        "run_id": run_id,
        "mode": mode.upper(),
        "status": status,
        "operation": operation,
        "provider": "github",
        "repository_id_hash": _hash(repository),
        "idempotency_key_hash": _hash_text(deduplication_key),
        "issue_id_hash": issue_id_hash,
        "remote_operations": remote_operations,
    }
    errors = _schema_errors(result, load_json(SCHEMA_PATH))
    if errors:
        raise _error("evidence violates its schema: " + "; ".join(errors), "repair the sandbox contract before a live run")
    return result


def _preflight(provider: GithubSandboxProvider, repository: str) -> None:
    try:
        details = provider.get_repository(repository)
    except AttributeError as exc:
        raise _error("provider cannot perform repository preflight", "use the dedicated GitHub provider with repository READ support") from exc
    if details.get("full_name") != repository:
        raise _error("repository identity did not match the approved target", "stop before Issue search and verify the sandbox")
    if details.get("archived") is True:
        raise _error("approved sandbox is archived", "use an active dedicated repository")
    if details.get("has_issues") is not True:
        raise _error("Issues are not enabled in the approved sandbox", "enable Issues only in the dedicated sandbox")
    if details.get("push_permission") is not True:
        raise _error("token lacks repository write permission", "use an external credential with permission only for the approved sandbox")


def _retry_settings(policy: Mapping[str, object]) -> tuple[int, float, float, float]:
    retry = policy["post_create_search"]
    return (
        retry["max_attempts"],
        float(retry["initial_delay_seconds"]),
        float(retry["backoff_multiplier"]),
        float(retry["max_delay_seconds"]),
    )


def _search_after_create(
    provider: GithubSandboxProvider,
    repository: str,
    deduplication_key: str,
    policy: Mapping[str, object],
    remote_operations: list[dict],
    sleep=time.sleep,
) -> list[dict]:
    max_attempts, delay, multiplier, max_delay = _retry_settings(policy)
    for attempt in range(max_attempts):
        matches = provider.search(repository, deduplication_key)
        remote_operations.append(_remote("READ", repository, deduplication_key, attempt=attempt + 1))
        if matches:
            return matches
        if attempt + 1 < max_attempts:
            sleep(delay)
            delay = min(max_delay, delay * multiplier)
    return []


def run_check(
    *,
    mode: str = "plan",
    confirm_live: bool = False,
    provider: GithubSandboxProvider | None = None,
    policy: Mapping[str, object] | None = None,
    manifest: Mapping[str, object] | None = None,
    run_id: str = "INITIAL-OPS-GITHUB-SANDBOX:attempt-1",
    repository_override: str | None = None,
    attempt_id: str | None = None,
    sleep=time.sleep,
) -> dict:
    if mode not in {"plan", "live"} or not ID_PATTERN.fullmatch(run_id):
        raise _error("mode or run ID is invalid", "use plan/live and a stable run ID")
    policy = policy or load_yaml(POLICY_PATH)
    manifest = manifest or load_yaml(MANIFEST_PATH)
    contract_errors = validate_github_sandbox_live_contract(dict(policy), load_json(SCHEMA_PATH), dict(manifest))
    if contract_errors:
        raise _error("policy is invalid: " + "; ".join(contract_errors), "repair the dedicated sandbox contract before use")

    if mode == "plan":
        effective_attempt_id = _validate_attempt_id(policy["fixture_attempt_id"] if attempt_id is None else attempt_id)
        deduplication_key = _deduplication_key(policy, effective_attempt_id)
        repository = policy["approved_repository"]["fixture_id"]
        return _result(
            run_id=run_id,
            mode=mode,
            status="PLANNED",
            operation="NONE",
            repository=repository,
            deduplication_key=deduplication_key,
            issue_id_hash=None,
            remote_operations=[],
        )
    if confirm_live is not True:
        raise _error("live mode requires explicit confirmation", "pass --confirm-live only for the approved sandbox")
    if attempt_id is None and not isinstance(provider, FixtureProvider):
        raise _error("live mode requires an attempt ID", "pass --attempt-id for every live qualification")
    effective_attempt_id = _validate_attempt_id(policy["fixture_attempt_id"] if attempt_id is None else attempt_id)
    deduplication_key = _deduplication_key(policy, effective_attempt_id)
    repository = repository_override or _repository_from_environment(policy)
    if FULL_NAME_PATTERN.fullmatch(repository) is None:
        raise _error("approved sandbox repository is not owner/name", "set a GitHub repository full name without a URL")
    if repository in _production_repositories(manifest):
        raise _error("production repository is not eligible for sandbox qualification", "set a separately designated repository")
    if provider is None:
        raise _error("live mode has no provider", "inject an authenticated GitHub provider")
    _preflight(provider, repository)

    remote_operations = [_remote("READ", repository, deduplication_key)]
    matches = provider.search(repository, deduplication_key)
    if len(matches) > 1:
        return _result(
            run_id=run_id,
            mode=mode,
            status="BLOCKED",
            operation="NONE",
            repository=repository,
            deduplication_key=deduplication_key,
            issue_id_hash=None,
            remote_operations=remote_operations,
        )
    if matches:
        number, _, issue_hash = _issue_ref(repository, matches[0])
        remote_operations.append(_remote("REUSE", repository, deduplication_key, number))
        return _result(
            run_id=run_id,
            mode=mode,
            status="REUSED",
            operation="REUSE",
            repository=repository,
            deduplication_key=deduplication_key,
            issue_id_hash=issue_hash,
            remote_operations=remote_operations,
        )

    created = provider.create(repository, "[sandbox] initial operations qualification", _body(repository, deduplication_key))
    number, _, issue_hash = _issue_ref(repository, created)
    remote_operations.append(_remote("CREATE", repository, deduplication_key, number))
    replay = _search_after_create(provider, repository, deduplication_key, policy, remote_operations, sleep=sleep)
    if len(replay) != 1:
        return _result(
            run_id=run_id,
            mode=mode,
            status="BLOCKED",
            operation="CREATE",
            repository=repository,
            deduplication_key=deduplication_key,
            issue_id_hash=issue_hash,
            remote_operations=remote_operations,
        )
    replay_number, _, replay_hash = _issue_ref(repository, replay[0])
    if replay_number != number or replay_hash != issue_hash:
        return _result(
            run_id=run_id,
            mode=mode,
            status="BLOCKED",
            operation="CREATE",
            repository=repository,
            deduplication_key=deduplication_key,
            issue_id_hash=issue_hash,
            remote_operations=remote_operations,
        )
    remote_operations.append(_remote("REUSE", repository, deduplication_key, number))
    return _result(
        run_id=run_id,
        mode=mode,
        status="CREATED",
        operation="CREATE",
        repository=repository,
        deduplication_key=deduplication_key,
        issue_id_hash=issue_hash,
        remote_operations=remote_operations,
    )


class FixtureProvider:
    """Networkless provider for proving the live lane's operation sequence."""

    def __init__(self, existing: Mapping[str, list[dict]] | list[dict] | None = None) -> None:
        if isinstance(existing, Mapping):
            self.existing = {key: list(value) for key, value in existing.items()}
        elif isinstance(existing, list):
            self.existing = {"*": list(existing)}
        else:
            self.existing = {}
        self.created: list[dict] = []

    def get_repository(self, repository: str) -> dict:
        return {"full_name": repository, "archived": False, "has_issues": True, "push_permission": True}

    def search(self, repository: str, deduplication_key: str) -> list[dict]:
        return list(self.existing.get(f"{repository}:{deduplication_key}", self.existing.get("*", [])))

    def create(self, repository: str, title: str, body: str) -> dict:
        deduplication_key = _extract_deduplication_key(body)
        scoped_key = f"{repository}:{deduplication_key}"
        all_existing = [item for values in self.existing.values() for item in values]
        number = max((item["number"] for item in all_existing), default=0) + 1
        result = {"number": number, "url": f"https://github.com/{repository}/issues/{number}"}
        self.created.append({"title": title, "body": body})
        self.existing.setdefault(scoped_key, []).append(result)
        return result


def _write_or_check(result: dict, output: Path, check: bool) -> None:
    content = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != content:
            raise _error("sandbox evidence is missing or stale", "run without --check to materialize the deterministic plan")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute the dedicated GitHub sandbox Issue qualification")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--fixture", action="store_true", help="use a networkless provider for contract tests")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--attempt-id", help="required live qualification attempt ID")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.plan and args.live:
            raise _error("--plan and --live cannot be combined", "select one mode")
        mode = "live" if args.live else "plan"
        policy = load_yaml(POLICY_PATH)
        if mode == "live" and not args.fixture and args.attempt_id is None:
            raise _error("live mode requires --attempt-id", "pass --attempt-id for every live qualification")
        provider = None
        if mode == "live" and args.fixture:
            provider = FixtureProvider()
        elif mode == "live":
            token = next((os.environ.get(name, "") for name in policy["token_env_vars"] if os.environ.get(name, "")), "")
            if not token:
                raise _error("live mode requires a GitHub token", "set GITHUB_TOKEN or GH_TOKEN outside Git and retry with --confirm-live")
            provider = GithubApiProvider(token)
        if args.fixture and mode == "plan":
            raise _error("--fixture is only meaningful with --live", "use --plan for the networkless plan")
        fixture_repository = "fixture-owner/fixture-github-live-sandbox" if args.fixture else None
        attempt_id = args.attempt_id if args.attempt_id is not None else (policy["fixture_attempt_id"] if args.fixture else None)
        result = run_check(
            mode=mode,
            confirm_live=args.confirm_live,
            provider=provider,
            repository_override=fixture_repository,
            attempt_id=attempt_id,
            policy=policy,
        )
        output = args.output if args.output.is_absolute() else Path.cwd() / args.output
        _write_or_check(result, output.resolve(), args.check)
        print(json.dumps({"command": "github-sandbox-live-check", "changed": not args.check, "mode": mode, "status": result["status"], "remote_operation_count": len(result["remote_operations"])}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] != "BLOCKED" else 1
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
