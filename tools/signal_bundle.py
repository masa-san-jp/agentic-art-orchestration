#!/usr/bin/env python3
"""Create and validate the parent-owned normalized signal bundle."""

from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from tools.validate import validate_signal
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.validate import validate_signal


CONTRACT = "normalized-research-signal-bundle/v1"
SIGNAL_KINDS = {"self", "art-history", "marketing"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)


def _error(source: str, detail: str, remediation: str) -> str:
    return f"{source}: {detail}; remediation: {remediation}"


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            _error(str(path), "JSON is not valid UTF-8", "provide one normalized signal object")
        ) from exc
    if not isinstance(value, dict):
        raise ValueError(_error(str(path), "JSON must contain an object", "provide one normalized signal object"))
    return value


def _timestamp(value: object) -> bool:
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validate_signal_bundle(bundle: dict[str, Any], source: str = "signal-bundle") -> list[str]:
    """Validate the aggregate envelope without weakening per-signal validation."""
    errors: list[str] = []
    if not isinstance(bundle, dict):
        return [_error(source, "bundle must be an object", "provide the canonical signal bundle envelope")]
    if bundle.get("contract_version") != CONTRACT:
        errors.append(_error(f"{source}.contract_version", "unsupported bundle contract", f"use {CONTRACT}"))

    generated_at = bundle.get("generated_at")
    if not _timestamp(generated_at):
        errors.append(_error(f"{source}.generated_at", "must be an RFC 3339 timestamp", "supply a deterministic generated_at value"))

    repositories = bundle.get("source_repositories")
    if not isinstance(repositories, list) or not repositories:
        errors.append(_error(f"{source}.source_repositories", "must be a non-empty list", "record every input repository commit"))
    else:
        seen_repositories: set[str] = set()
        for index, item in enumerate(repositories):
            prefix = f"{source}.source_repositories[{index}]"
            if not isinstance(item, dict):
                errors.append(_error(prefix, "must be an object", "record repository metadata"))
                continue
            repository = item.get("repository")
            commit = item.get("commit")
            count = item.get("record_count")
            if not isinstance(repository, str) or not repository:
                errors.append(_error(f"{prefix}.repository", "must be non-empty", "record the child repository ID"))
            elif repository in seen_repositories:
                errors.append(_error(f"{prefix}.repository", "is duplicated", "provide one record per repository"))
            else:
                seen_repositories.add(repository)
            if not isinstance(commit, str) or not SHA40.fullmatch(commit):
                errors.append(_error(f"{prefix}.commit", "must be a 40-character lowercase SHA", "preserve immutable child provenance"))
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                errors.append(_error(f"{prefix}.record_count", "must be a positive integer", "record the number of exported signals"))

    records = bundle.get("records")
    if not isinstance(records, list) or not records:
        errors.append(_error(f"{source}.records", "must be a non-empty list", "provide normalized signal records"))
        return errors

    seen_ids: set[str] = set()
    seen_kinds: set[str] = set()
    repository_map = {
        item.get("repository"): item
        for item in repositories
        if isinstance(item, dict) and isinstance(item.get("repository"), str)
    } if isinstance(repositories, list) else {}
    for index, signal in enumerate(records):
        record_source = f"{source}.records[{index}]"
        if not isinstance(signal, dict):
            errors.append(_error(record_source, "must be an object", "export normalized signal objects"))
            continue
        signal_id = signal.get("signal_id")
        signal_kind = signal.get("signal_kind")
        if not isinstance(signal_id, str) or not signal_id:
            errors.append(_error(f"{record_source}.signal_id", "must be non-empty", "preserve the child signal ID"))
        elif signal_id in seen_ids:
            errors.append(_error(f"{record_source}.signal_id", "is duplicated", "retain one immutable signal per ID"))
        else:
            seen_ids.add(signal_id)
        if signal_kind not in SIGNAL_KINDS:
            errors.append(_error(f"{record_source}.signal_kind", "is outside the v1 vocabulary", "use self, art-history, or marketing"))
        else:
            seen_kinds.add(signal_kind)
        errors.extend(validate_signal(signal, record_source))

        source_data = signal.get("source")
        if not isinstance(source_data, dict):
            continue
        repository = source_data.get("repository")
        commit = source_data.get("commit")
        metadata = repository_map.get(repository)
        if metadata is None:
            errors.append(_error(f"{record_source}.source.repository", "is absent from source_repositories", "record every source repository in the envelope"))
        else:
            if metadata.get("commit") != commit:
                errors.append(_error(f"{record_source}.source.commit", "differs from source_repositories", "re-export from one immutable child snapshot"))

    missing_kinds = sorted(SIGNAL_KINDS - seen_kinds)
    if missing_kinds:
        errors.append(_error(f"{source}.records", f"missing signal kinds {missing_kinds}", "export one approved signal from each input KB"))
    if isinstance(repositories, list):
        observed_counts: dict[str, int] = {}
        for signal in records:
            if isinstance(signal, dict) and isinstance(signal.get("source"), dict):
                repository = signal["source"].get("repository")
                observed_counts[repository] = observed_counts.get(repository, 0) + 1
        for repository, metadata in repository_map.items():
            if metadata.get("record_count") != observed_counts.get(repository, 0):
                errors.append(_error(f"{source}.source_repositories[{repository}]", "record_count does not match records", "regenerate the aggregate bundle from the same snapshot"))
    return errors


def build_signal_bundle(signals: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    """Build a deterministic aggregate bundle from normalized records only."""
    if not isinstance(signals, list) or not signals:
        raise ValueError(_error("signal-bundle", "signals must be non-empty", "export normalized signals from the input KBs"))
    records = sorted((copy.deepcopy(signal) for signal in signals), key=lambda signal: signal.get("signal_id", ""))
    repositories: dict[str, dict[str, Any]] = {}
    for signal in records:
        if not isinstance(signal, dict):
            raise ValueError(_error("signal-bundle", "every record must be an object", "export normalized signal objects"))
        source = signal.get("source") or {}
        repository = source.get("repository")
        commit = source.get("commit")
        if not isinstance(repository, str) or not isinstance(commit, str):
            raise ValueError(_error("signal-bundle", "every record needs repository and commit", "preserve source provenance before aggregation"))
        entry = repositories.setdefault(repository, {"repository": repository, "commit": commit, "record_count": 0})
        if entry["commit"] != commit:
            raise ValueError(_error("signal-bundle", f"repository {repository!r} has multiple commits", "build a bundle from one immutable child snapshot"))
        entry["record_count"] += 1
    bundle = {
        "contract_version": CONTRACT,
        "generated_at": generated_at,
        "source_repositories": [repositories[key] for key in sorted(repositories)],
        "records": records,
    }
    errors = validate_signal_bundle(bundle)
    if errors:
        raise ValueError("\n".join(errors))
    return bundle


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self", dest="self_signal", type=Path, required=True)
    parser.add_argument("--art-history", type=Path, required=True)
    parser.add_argument("--marketing", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        bundle = build_signal_bundle(
            [load_json(path) for path in (args.self_signal, args.art_history, args.marketing)],
            args.generated_at,
        )
        rendered = json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.check:
            if args.output.read_text(encoding="utf-8") != rendered:
                raise ValueError(_error(str(args.output), "generated bytes differ", "regenerate the canonical signal bundle"))
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(json.dumps({"command": "signal-bundle", "record_count": len(bundle["records"]), "status": "PASSED"}, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
