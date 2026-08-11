#!/usr/bin/env python3
"""Select a deterministic, provenance-preserving package from passing candidates."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

try:
    from tools.candidate_gates import build_gate_report
    from tools.candidate_space import DEFAULT_FIXTURE_DIR, DEFAULT_OUTPUT_PATH as DEFAULT_CANDIDATE_PATH, build_candidate_space, canonical_json, load_fixture
    from tools.validate import (
        ROOT,
        TRANSFORMATION_RULE_CONFIG_PATH,
        load_json,
        load_yaml,
        validate_candidate_gates,
        validate_candidate_space,
        validate_selection,
        validate_signal,
        validate_transformation_rule_registry,
    )
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.candidate_gates import build_gate_report
    from tools.candidate_space import DEFAULT_FIXTURE_DIR, DEFAULT_OUTPUT_PATH as DEFAULT_CANDIDATE_PATH, build_candidate_space, canonical_json, load_fixture
    from tools.validate import (
        ROOT,
        TRANSFORMATION_RULE_CONFIG_PATH,
        load_json,
        load_yaml,
        validate_candidate_gates,
        validate_candidate_space,
        validate_selection,
        validate_signal,
        validate_transformation_rule_registry,
    )


DEFAULT_OUTPUT_PATH = ROOT / "data/selection.json"
SIGNAL_KINDS = ("self", "art-history", "marketing")


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _error(source: str, detail: str, remediation: str) -> str:
    return f"{source}: {detail}; remediation: {remediation}"


def _copy_candidate(candidate: dict, rank: int, score: str) -> dict:
    return {
        "candidate_id": candidate["candidate_id"],
        "rule_id": candidate["rule_id"],
        "rank": rank,
        "selection_score": score,
        "inputs": copy.deepcopy(candidate["inputs"]),
        "composition": copy.deepcopy(candidate["composition"]),
    }


def build_selection(
    candidate_space: dict,
    gate_report: dict,
    project_id: str,
    seed_input: str = "default",
    selection_limit: int = 1,
    source: str = "selection",
) -> dict:
    """Select top passing candidates using SHA-256 ordering independent of runtime PRNGs."""
    candidate_errors = validate_candidate_space(candidate_space, f"{source}.candidates")
    gate_errors = validate_candidate_gates(gate_report, f"{source}.gates")
    if candidate_errors or gate_errors:
        raise ValueError("\n".join(candidate_errors + gate_errors))
    if not isinstance(project_id, str) or not project_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in project_id):
        raise ValueError(_error(source, f"invalid project_id {project_id!r}", "use a stable project identifier without whitespace or shell syntax"))
    if not isinstance(seed_input, str) or not seed_input or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for char in seed_input):
        raise ValueError(_error(source, f"invalid seed_input {seed_input!r}", "use a stable seed label without whitespace or shell syntax"))
    if not isinstance(selection_limit, int) or isinstance(selection_limit, bool) or selection_limit < 1:
        raise ValueError(_error(source, "selection_limit must be a positive integer", "select at least one passing candidate"))

    seed = sha256_hex(
        {
            "project_id": project_id,
            "snapshot_id": candidate_space["snapshot_id"],
            "rule_set_hash": candidate_space["rule_set_hash"],
            "seed_input": seed_input,
        }
    )
    gate_by_id = {evaluation["candidate_id"]: evaluation for evaluation in gate_report["evaluations"]}
    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in candidate_space["candidates"]}
    passing: list[tuple[str, dict]] = []
    for candidate_id, candidate in candidates_by_id.items():
        evaluation = gate_by_id.get(candidate_id)
        if evaluation is None:
            raise ValueError(_error(source, f"candidate {candidate_id!r} has no gate evaluation", "evaluate every candidate before selection"))
        if evaluation["overall_status"] == "PASS":
            score = sha256_hex({"seed": seed, "candidate_id": candidate_id})
            passing.append((score, candidate))
    if not passing:
        raise ValueError(_error(source, "no candidate passed all gates", "reject the selection and retain gate evidence"))
    passing.sort(key=lambda item: (item[0], item[1]["candidate_id"]), reverse=True)
    selected = [
        _copy_candidate(candidate, rank, score)
        for rank, (score, candidate) in enumerate(passing[:selection_limit], start=1)
    ]
    result = {
        "contract_version": "research-selection/v1",
        "project_id": project_id,
        "snapshot_id": candidate_space["snapshot_id"],
        "rule_set_hash": candidate_space["rule_set_hash"],
        "candidate_space_hash": sha256_hex(candidate_space),
        "gate_report_hash": sha256_hex(gate_report),
        "seed_input": seed_input,
        "seed": seed,
        "selection_limit": selection_limit,
        "selected_count": len(selected),
        "selected_candidates": selected,
    }
    errors = validate_selection(result, source)
    if errors:
        raise ValueError("\n".join(errors))
    return result


def load_runtime_inputs(candidate_path: Path, fixture_dir: Path, rules_path: Path) -> tuple[dict, dict]:
    candidate_space = load_json(candidate_path)
    signals = load_fixture(fixture_dir)
    registry = load_yaml(rules_path)
    return candidate_space, build_gate_report(candidate_space, signals, registry)


def _render(data: dict) -> bytes:
    return (canonical_json(data) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Select passing v1.2 candidates with a stable derived seed")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATE_PATH)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--rules", type=Path, default=TRANSFORMATION_RULE_CONFIG_PATH)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--seed-input", default="default")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--check", action="store_true", help="compare generated bytes without writing")
    args = parser.parse_args()
    try:
        candidate_space, gate_report = load_runtime_inputs(args.candidates, args.fixture, args.rules)
        result = build_selection(candidate_space, gate_report, args.project_id, args.seed_input, args.limit)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rendered = _render(result)
    if args.check:
        try:
            observed = args.output.read_bytes()
        except OSError as exc:
            print(f"ERROR: {args.output}: {exc}; remediation: generate the selection artifact first", file=sys.stderr)
            return 1
        if observed != rendered:
            print(f"ERROR: {args.output}: generated selection bytes differ; remediation: regenerate the deterministic artifact", file=sys.stderr)
            return 1
        changed = False
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        changed = args.output.exists() and args.output.read_bytes() == rendered
        if not changed:
            args.output.write_bytes(rendered)
    print(
        json.dumps(
            {"changed": not changed if not args.check else False, "command": "selection", "selected_count": result["selected_count"], "status": "PASSED"},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
