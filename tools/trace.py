#!/usr/bin/env python3
"""Build a deterministic requirement-to-source provenance trace."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from tools.validate import validate_signal
except ModuleNotFoundError:  # direct execution as `python3 tools/trace.py`
    sys.path.insert(0, str(ROOT))
    from tools.validate import validate_signal


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _error(detail: str, remediation: str) -> str:
    return f"{detail}; remediation: {remediation}"


def load_portfolio(fixture_root: Path) -> tuple[dict, dict[str, dict], list[str]]:
    errors: list[str] = []
    portfolio_path = fixture_root / "portfolio.json"
    try:
        with portfolio_path.open(encoding="utf-8") as handle:
            portfolio = json.load(handle)
    except Exception as exc:
        return {}, {}, [_error(f"{portfolio_path}: JSON parse failed: {exc}", "repair portfolio.json")]
    if not isinstance(portfolio, dict):
        return {}, {}, [_error("portfolio must be an object", "provide portfolio.json as an object")]
    if portfolio.get("version") != 1:
        errors.append(_error("portfolio.version must be 1", "use the supported trace fixture version"))
    signal_files = portfolio.get("signal_files")
    if not isinstance(signal_files, list) or not signal_files:
        errors.append(_error("portfolio.signal_files must be non-empty", "list normalized signal fixture paths"))
        return portfolio, {}, errors

    signals: dict[str, dict] = {}
    for index, relative in enumerate(signal_files):
        if not isinstance(relative, str) or not relative:
            errors.append(_error(f"signal_files[{index}] must be a path", "use a relative JSON fixture path"))
            continue
        signal_path = (fixture_root / relative).resolve()
        if not signal_path.is_file():
            errors.append(_error(f"signal fixture missing: {relative!r}", "add the referenced signal fixture"))
            continue
        try:
            with signal_path.open(encoding="utf-8") as handle:
                signal = json.load(handle)
        except Exception as exc:
            errors.append(_error(f"{relative}: JSON parse failed: {exc}", "repair the signal fixture"))
            continue
        signal_errors = validate_signal(signal, f"fixture:{relative}")
        if signal_errors:
            errors.extend(signal_errors)
            continue
        signal_id = signal.get("signal_id")
        if signal_id in signals:
            errors.append(_error(f"duplicate signal_id {signal_id!r}", "declare each source signal once"))
        else:
            signals[signal_id] = signal
    return portfolio, signals, errors


def build_trace(fixture_root: Path) -> tuple[dict | None, list[str]]:
    portfolio, signals, errors = load_portfolio(fixture_root)
    if errors:
        return None, errors
    requirements = portfolio.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        return None, [_error("portfolio.requirements must be non-empty", "declare each research requirement")]

    seen_requirements: set[str] = set()
    traced_signal_ids: set[str] = set()
    traced_requirements: list[dict] = []
    for index, requirement in enumerate(requirements):
        prefix = f"requirements[{index}]"
        if not isinstance(requirement, dict):
            errors.append(_error(f"{prefix} must be an object", "declare requirement id and signal_ids"))
            continue
        requirement_id = requirement.get("id")
        if not isinstance(requirement_id, str) or not requirement_id:
            errors.append(_error(f"{prefix}.id is required", "assign a stable requirement ID"))
            continue
        if requirement_id in seen_requirements:
            errors.append(_error(f"duplicate requirement id {requirement_id!r}", "declare each requirement once"))
            continue
        seen_requirements.add(requirement_id)
        signal_ids = requirement.get("signal_ids")
        if not isinstance(signal_ids, list) or not signal_ids:
            errors.append(_error(f"{prefix}.signal_ids must be non-empty", "link the requirement to source signals"))
            continue
        edges: list[dict] = []
        for signal_id in signal_ids:
            signal = signals.get(signal_id)
            if signal is None:
                errors.append(_error(
                    f"{prefix}.signal_ids references unknown {signal_id!r}",
                    "reference a signal declared in signal_files",
                ))
                continue
            source = signal["source"]
            evidence_locators = [ref["locator"] for ref in signal["evidence_refs"]]
            edges.append(
                {
                    "signal_id": signal["signal_id"],
                    "signal_kind": signal["signal_kind"],
                    "source_repository": source["repository"],
                    "source_commit": source["commit"],
                    "source_entity_ids": list(source["entity_ids"]),
                    "source_locators": list(source["locators"]),
                    "evidence_locators": evidence_locators,
                }
            )
            traced_signal_ids.add(signal_id)
        if edges:
            traced_requirements.append(
                {
                    "requirement_id": requirement_id,
                    "statement": requirement.get("statement", ""),
                    "edges": edges,
                }
            )

    if errors:
        return None, errors
    if len(traced_requirements) != len(requirements):
        return None, [_error("every requirement must have a trace edge", "link every requirement to a valid signal")]

    trace = {
        "version": 1,
        "requirements": traced_requirements,
        "signal_count": len(signals),
        "traced_signal_count": len(traced_signal_ids),
    }
    trace["trace_hash"] = hashlib.sha256(canonical_json(trace).encode("utf-8")).hexdigest()
    return trace, []


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate cross-repository provenance trace")
    parser.add_argument("--check", action="store_true", help="validate and print the deterministic trace")
    parser.add_argument("--fixture", type=Path, required=True, help="portfolio fixture directory")
    args = parser.parse_args()
    fixture_root = args.fixture if args.fixture.is_absolute() else Path.cwd() / args.fixture
    trace, errors = build_trace(fixture_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
