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
    from tools.candidate_space import (
        DEFAULT_FIXTURE_DIR,
        DEFAULT_OUTPUT_PATH as DEFAULT_CANDIDATE_PATH,
        build_candidate_space,
        canonical_json,
        eligible_personal_anchors,
        load_fixture,
    )
    from tools.validate import (
        ROOT,
        TRANSFORMATION_RULE_CONFIG_PATH,
        load_json,
        load_yaml,
        validate_candidate_gates,
        validate_candidate_space,
        validate_self_diversity_report,
        validate_selection,
        validate_signal,
        validate_transformation_rule_registry,
    )
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.candidate_gates import build_gate_report
    from tools.candidate_space import (
        DEFAULT_FIXTURE_DIR,
        DEFAULT_OUTPUT_PATH as DEFAULT_CANDIDATE_PATH,
        build_candidate_space,
        canonical_json,
        eligible_personal_anchors,
        load_fixture,
    )
    from tools.validate import (
        ROOT,
        TRANSFORMATION_RULE_CONFIG_PATH,
        load_json,
        load_yaml,
        validate_candidate_gates,
        validate_candidate_space,
        validate_self_diversity_report,
        validate_selection,
        validate_signal,
        validate_transformation_rule_registry,
    )


DEFAULT_OUTPUT_PATH = ROOT / "data/selection.json"
DEFAULT_DIVERSITY_OUTPUT_PATH = ROOT / "data/self-diversity-report.json"
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


def _signal_ids_by_kind(candidate: dict) -> dict[str, str]:
    """Extract the one selected signal ID per required kind from a candidate."""
    result: dict[str, str] = {}
    for kind in SIGNAL_KINDS:
        refs = candidate.get("inputs", {}).get(kind, [])
        ids = sorted({ref.get("signal_id") for ref in refs if isinstance(ref, dict) and isinstance(ref.get("signal_id"), str)})
        if len(ids) == 1:
            result[kind] = ids[0]
    return result


def _resolve_personal_anchor_id(
    candidate: dict,
    candidate_space: dict,
    signals: list[dict],
    anchors: list[dict] | None = None,
) -> str | None:
    """Resolve an anchor by replaying candidate identity without exposing its value."""
    slot = candidate.get("composition", {}).get("personal_tension", {})
    signal_id = slot.get("signal_id")
    attribute = slot.get("attribute")
    if attribute not in {"tensions", "recurring_patterns"} or not isinstance(signal_id, str):
        return None
    anchor_pool = anchors if anchors is not None else eligible_personal_anchors(signals)
    anchor_candidates = [
        anchor
        for anchor in anchor_pool
        if anchor["signal_id"] == signal_id and anchor["attribute"] == attribute
    ]
    signal_ids = _signal_ids_by_kind(candidate)
    if set(signal_ids) != set(SIGNAL_KINDS):
        return None
    base_identity = {
        "rule_id": candidate.get("rule_id"),
        "snapshot_id": candidate_space.get("snapshot_id"),
        "signal_ids": signal_ids,
    }
    for anchor in anchor_candidates:
        identity = {**base_identity, "personal_anchor_id": anchor["anchor_id"]}
        if candidate.get("candidate_id") == f"candidate:{sha256_hex(identity)[:16]}":
            return anchor["anchor_id"]
    if len(anchor_candidates) == 1 and candidate.get("candidate_id") == f"candidate:{sha256_hex(base_identity)[:16]}":
        return anchor_candidates[0]["anchor_id"]
    return None


def _selection_anchor_key(
    candidate: dict,
    candidate_space: dict,
    signals: list[dict] | None,
    anchors: list[dict] | None = None,
) -> str:
    if signals is not None:
        resolved = _resolve_personal_anchor_id(candidate, candidate_space, signals, anchors)
        if resolved is not None:
            return resolved
    slot = candidate.get("composition", {}).get("personal_tension", {})
    return f"{slot.get('signal_id', '')}\n{slot.get('attribute', '')}"


def _fair_order(
    passing: list[tuple[str, dict]],
    candidate_space: dict,
    signals: list[dict] | None,
) -> list[tuple[str, dict]]:
    """Schedule candidates round-robin by anchor, retaining hash order per anchor."""
    groups: dict[str, list[tuple[str, dict]]] = {}
    anchors = eligible_personal_anchors(signals) if signals is not None else None
    for score, candidate in passing:
        key = _selection_anchor_key(candidate, candidate_space, signals, anchors)
        groups.setdefault(key, []).append((score, candidate))
    for values in groups.values():
        values.sort(key=lambda item: (item[0], item[1]["candidate_id"]), reverse=True)
    anchor_order = sorted(
        groups,
        key=lambda key: (groups[key][0][0], key),
        reverse=True,
    )
    ordered: list[tuple[str, dict]] = []
    while True:
        added = False
        for key in anchor_order:
            if groups[key]:
                ordered.append(groups[key].pop(0))
                added = True
        if not added:
            return ordered


def build_self_diversity_report(
    signals: list[dict],
    candidate_space: dict,
    selected_candidates: list[dict] | None = None,
    selection_limit: int = 1,
    source: str = "self-diversity",
) -> dict:
    """Build a versioned, opaque report over consented self-model anchors."""
    candidate_errors = validate_candidate_space(candidate_space, f"{source}.candidates")
    if candidate_errors:
        raise ValueError("\n".join(candidate_errors))
    if not isinstance(selection_limit, int) or isinstance(selection_limit, bool) or selection_limit < 1:
        raise ValueError(_error(source, "selection_limit must be a positive integer", "use the requested candidate limit"))
    anchors = eligible_personal_anchors(signals, source)
    selected = selected_candidates if selected_candidates is not None else []
    selected_anchor_ids: list[str] = []
    for index, candidate in enumerate(selected):
        anchor_id = _resolve_personal_anchor_id(candidate, candidate_space, signals, anchors)
        if anchor_id is None:
            raise ValueError(
                _error(
                    source,
                    f"selected_candidates[{index}] has no eligible personal anchor",
                    "select only candidates generated from consented tensions or recurring_patterns",
                )
            )
        selected_anchor_ids.append(anchor_id)
    counts = {attribute: 0 for attribute in ("tensions", "recurring_patterns")}
    for anchor in anchors:
        counts[anchor["attribute"]] += 1
    frequencies = {anchor_id: selected_anchor_ids.count(anchor_id) for anchor_id in set(selected_anchor_ids)}
    selected_count = len(selected_anchor_ids)
    max_share = max((count / selected_count for count in frequencies.values()), default=0.0)
    distinct_count = len(frequencies)
    if len(anchors) < 3:
        status = "INSUFFICIENT_SELF_DIVERSITY"
    elif selected_count > selection_limit:
        status = "REJECT"
    elif selected_count and selected_count < selection_limit:
        status = "REJECT"
    elif selection_limit >= 10 and (distinct_count < 3 or max_share > 0.4):
        status = "REJECT"
    else:
        status = "PASS"
    self_signals = sorted(
        (signal for signal in signals if signal.get("signal_kind") == "self"),
        key=lambda signal: signal["signal_id"],
    )
    report = {
        "contract_version": "self-diversity-report/v1",
        "eligible_anchor_count": len(anchors),
        "attribute_counts": counts,
        "anchor_ids": [anchor["anchor_id"] for anchor in anchors],
        "selection_limit": selection_limit,
        "selected_count": selected_count,
        "distinct_selected_count": distinct_count,
        "selected_anchor_ids": selected_anchor_ids,
        "max_anchor_share": max_share,
        "status": status,
        "source": {
            "repository": "self-model",
            "signal_ids": [signal["signal_id"] for signal in self_signals],
            "source_commits": sorted({signal["source"]["commit"] for signal in self_signals}),
        },
    }
    errors = validate_self_diversity_report(report, source)
    if errors:
        raise ValueError("\n".join(errors))
    return report


def build_selection(
    candidate_space: dict,
    gate_report: dict,
    project_id: str,
    seed_input: str = "default",
    selection_limit: int = 1,
    source: str = "selection",
    require_self_diversity: bool = False,
    signals: list[dict] | None = None,
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
    if require_self_diversity and signals is None:
        raise ValueError(_error(source, "self-diversity enforcement requires normalized signals", "pass the exact consented signal export used to build candidates"))

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
    if require_self_diversity:
        report = build_self_diversity_report(signals or [], candidate_space, None, selection_limit, f"{source}.self-diversity")
        if report["status"] == "INSUFFICIENT_SELF_DIVERSITY":
            raise ValueError(_error(source, "INSUFFICIENT_SELF_DIVERSITY", "provide at least three eligible consented self-model anchors"))
        if len(passing) < selection_limit:
            raise ValueError(_error(source, "candidate shortage under self-diversity enforcement", "provide at least selection_limit passing candidates; do not lower the requested count"))
        passing = _fair_order(passing, candidate_space, signals)
    selected = [
        _copy_candidate(candidate, rank, score)
        for rank, (score, candidate) in enumerate(passing[:selection_limit], start=1)
    ]
    if require_self_diversity:
        report = build_self_diversity_report(signals or [], candidate_space, selected, selection_limit, f"{source}.self-diversity")
        if report["status"] != "PASS":
            raise ValueError(_error(source, f"self-diversity report status {report['status']!r}", "retain the full requested selection and satisfy the anchor distribution limits"))
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
    parser.add_argument("--require-self-diversity", action="store_true", help="enforce at least three consented self-model anchors")
    parser.add_argument("--diversity-report", type=Path, help="write the versioned self-diversity report")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--check", action="store_true", help="compare generated bytes without writing")
    args = parser.parse_args()
    try:
        candidate_space, gate_report = load_runtime_inputs(args.candidates, args.fixture, args.rules)
        signals = load_fixture(args.fixture) if args.require_self_diversity or args.diversity_report else None
        result = build_selection(
            candidate_space,
            gate_report,
            args.project_id,
            args.seed_input,
            args.limit,
            require_self_diversity=args.require_self_diversity,
            signals=signals,
        )
        if args.diversity_report:
            report = build_self_diversity_report(signals or [], candidate_space, result["selected_candidates"], args.limit)
            args.diversity_report.parent.mkdir(parents=True, exist_ok=True)
            args.diversity_report.write_bytes(_render(report))
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
