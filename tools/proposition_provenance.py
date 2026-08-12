#!/usr/bin/env python3
"""Build a deterministic, reference-only provenance trace for selected propositions."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

try:
    from tools.candidate_space import DEFAULT_FIXTURE_DIR, canonical_json, load_fixture
    from tools.validate import (
        ROOT,
        TRANSFORMATION_RULE_CONFIG_PATH,
        load_json,
        load_yaml,
        validate_candidate_gates,
        validate_candidate_space,
        validate_research_provenance,
        validate_selection,
        validate_signal,
        validate_transformation_rule_registry,
    )
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.candidate_space import DEFAULT_FIXTURE_DIR, canonical_json, load_fixture
    from tools.validate import (
        ROOT,
        TRANSFORMATION_RULE_CONFIG_PATH,
        load_json,
        load_yaml,
        validate_candidate_gates,
        validate_candidate_space,
        validate_research_provenance,
        validate_selection,
        validate_signal,
        validate_transformation_rule_registry,
    )


DEFAULT_CANDIDATE_PATH = ROOT / "data/candidate-space.json"
DEFAULT_GATE_PATH = ROOT / "data/candidate-gates.json"
DEFAULT_SELECTION_PATH = ROOT / "data/selection.json"
DEFAULT_OUTPUT_PATH = ROOT / "data/provenance.json"
SIGNAL_KINDS = ("self", "art-history", "marketing")
TEMPLATE = "{personal_tension} is externalized through {historical_operation} against {contemporary_condition}"


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _error(source: str, detail: str, remediation: str) -> str:
    return f"{source}: {detail}; remediation: {remediation}"


def _source_ref(signal: dict) -> dict:
    source = signal["source"]
    return {
        "source_repository": source["repository"],
        "source_commit": source["commit"],
        "source_entity_ids": list(source["entity_ids"]),
        "source_locators": list(source["locators"]),
        "evidence_locators": [item["locator"] for item in signal["evidence_refs"]],
    }


def _ref_matches_signal(ref: dict, signal: dict) -> bool:
    expected = _source_ref(signal)
    return (
        ref.get("signal_id") == signal.get("signal_id")
        and ref.get("signal_kind") == signal.get("signal_kind")
        and ref.get("source_repository") == expected["source_repository"]
        and ref.get("source_commit") == expected["source_commit"]
        and ref.get("source_entity_ids") == expected["source_entity_ids"]
        and ref.get("source_locators") == expected["source_locators"]
        and ref.get("evidence_locators") == expected["evidence_locators"]
    )


def _slot_provenance(slot: dict, signal: dict) -> dict:
    source = _source_ref(signal)
    return {
        "signal_id": slot["signal_id"],
        "signal_kind": slot["signal_kind"],
        "attribute": slot["attribute"],
        "source_repository": source["source_repository"],
        "source_commit": source["source_commit"],
        "evidence_locator": source["evidence_locators"][0],
    }


def _signal_trace(signal: dict, attributes: list[str]) -> dict:
    return {
        "signal_id": signal["signal_id"],
        "signal_kind": signal["signal_kind"],
        "attributes": sorted(set(attributes)),
        **_source_ref(signal),
    }


def _validate_inputs(
    selection: dict,
    candidate_space: dict,
    gate_report: dict,
    signals: list[dict],
    registry: dict,
    source: str,
) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    errors: list[str] = []
    errors.extend(validate_selection(selection, f"{source}.selection"))
    errors.extend(validate_candidate_space(candidate_space, f"{source}.candidates"))
    errors.extend(validate_candidate_gates(gate_report, f"{source}.gates"))
    errors.extend(validate_transformation_rule_registry(registry, f"{source}.rules"))
    signal_by_id: dict[str, dict] = {}
    for index, signal in enumerate(signals):
        signal_errors = validate_signal(signal, f"{source}.signals[{index}]")
        errors.extend(signal_errors)
        signal_id = signal.get("signal_id") if isinstance(signal, dict) else None
        if isinstance(signal_id, str):
            if signal_id in signal_by_id:
                errors.append(_error(source, f"duplicate signal_id {signal_id!r}", "provide one normalized signal per stable ID"))
            signal_by_id[signal_id] = signal
    if errors:
        raise ValueError("\n".join(errors))
    expected_candidate_hash = sha256_hex(candidate_space)
    expected_gate_hash = sha256_hex(gate_report)
    if selection["candidate_space_hash"] != expected_candidate_hash:
        errors.append(_error(source, "selection candidate_space_hash does not match candidate input", "trace the exact candidate artifact used for selection"))
    if selection["gate_report_hash"] != expected_gate_hash:
        errors.append(_error(source, "selection gate_report_hash does not match gate input", "trace the exact gate artifact used for selection"))
    for field in ("snapshot_id", "rule_set_hash"):
        if selection[field] != candidate_space[field]:
            errors.append(_error(source, f"selection {field} does not match candidate space", "preserve the snapshot and rule registry identity through selection"))
    if gate_report["candidate_space_hash"] != expected_candidate_hash:
        errors.append(_error(source, "gate report candidate_space_hash does not match candidate input", "evaluate the exact candidate artifact being selected"))
    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in candidate_space["candidates"]}
    evaluations_by_id = {evaluation["candidate_id"]: evaluation for evaluation in gate_report["evaluations"]}
    rules_by_id = {rule["rule_id"]: rule for rule in registry["rules"] if rule.get("status") == "active"}
    for selected in selection["selected_candidates"]:
        candidate = candidates_by_id.get(selected["candidate_id"])
        if candidate is None:
            errors.append(_error(source, f"selection references unknown candidate {selected['candidate_id']!r}", "select only candidates from the same immutable candidate space"))
            continue
        if selected.get("inputs") != candidate["inputs"] or selected.get("composition") != candidate["composition"]:
            errors.append(_error(source, f"selection candidate {selected['candidate_id']!r} differs from candidate space", "preserve the selected candidate references exactly"))
        evaluation = evaluations_by_id.get(selected["candidate_id"])
        if evaluation is None or evaluation["overall_status"] != "PASS":
            errors.append(_error(source, f"selection candidate {selected['candidate_id']!r} lacks a passing gate evaluation", "trace only candidates that passed every specificity gate"))
        if candidate["rule_id"] not in rules_by_id:
            errors.append(_error(source, f"candidate references unknown active rule {candidate['rule_id']!r}", "trace only an active rule from the immutable registry"))
        for kind in SIGNAL_KINDS:
            for ref in candidate["inputs"][kind]:
                signal = signal_by_id.get(ref["signal_id"])
                if signal is None:
                    errors.append(_error(source, f"candidate input references unknown signal {ref['signal_id']!r}", "preserve every normalized signal used by the candidate"))
                    continue
                if not _ref_matches_signal(ref, signal):
                    errors.append(_error(source, f"candidate input {ref['signal_id']!r} loses source provenance", "copy source repository, commit, entity, and evidence locators exactly"))
                domain_key = {"self": "self_model", "art-history": "art_history", "marketing": "marketing"}[kind]
                domain = signal.get("domain", {}).get(domain_key, {})
                if ref["attribute"] not in domain:
                    errors.append(_error(source, f"candidate input {ref['signal_id']!r} references absent attribute {ref['attribute']!r}", "bind only an attribute present in the normalized signal"))
    if errors:
        raise ValueError("\n".join(errors))
    return signal_by_id, candidates_by_id, rules_by_id


def build_provenance(
    selection: dict,
    candidate_space: dict,
    gate_report: dict,
    signals: list[dict],
    registry: dict,
    source: str = "provenance",
) -> dict:
    """Trace every selected passing candidate without generating ungrounded wording."""
    signal_by_id, candidates_by_id, rules_by_id = _validate_inputs(
        selection, candidate_space, gate_report, signals, registry, source
    )
    selection_refs = [
        {
            "candidate_id": selected["candidate_id"],
            "rank": selected["rank"],
            "selection_score": selected["selection_score"],
        }
        for selected in selection["selected_candidates"]
    ]
    propositions: list[dict] = []
    for selected in sorted(selection["selected_candidates"], key=lambda item: item["rank"]):
        candidate = candidates_by_id[selected["candidate_id"]]
        rule = rules_by_id[candidate["rule_id"]]
        attributes_by_signal: dict[str, list[str]] = {}
        for kind in SIGNAL_KINDS:
            for ref in candidate["inputs"][kind]:
                attributes_by_signal.setdefault(ref["signal_id"], []).append(ref["attribute"])
        normalized_signals = [
            _signal_trace(signal_by_id[signal_id], attributes_by_signal[signal_id])
            for signal_id in sorted(attributes_by_signal)
        ]
        slots = {
            slot_name: _slot_provenance(
                candidate["composition"][slot_name],
                signal_by_id[candidate["composition"][slot_name]["signal_id"]],
            )
            for slot_name in sorted(candidate["composition"])
        }
        proposition_id = f"proposition:{sha256_hex({'project_id': selection['project_id'], 'snapshot_id': selection['snapshot_id'], 'candidate_id': candidate['candidate_id'], 'seed': selection['seed']})[:16]}"
        propositions.append(
            {
                "proposition_id": proposition_id,
                "candidate_id": candidate["candidate_id"],
                "rule_id": candidate["rule_id"],
                "selection": {
                    "candidate_id": selected["candidate_id"],
                    "rank": selected["rank"],
                    "selection_score": selected["selection_score"],
                },
                "candidate": copy.deepcopy(candidate),
                "rule": {
                    "rule_id": rule["rule_id"],
                    "rule_set_hash": candidate_space["rule_set_hash"],
                    "output_type": rule["composition"]["output_type"],
                    "template": rule["composition"]["template"],
                    "constraints": list(rule["constraints"]),
                },
                "structured_output": {
                    "output_type": rule["composition"]["output_type"],
                    "template": rule["composition"]["template"],
                    "slots": slots,
                },
                "normalized_signals": normalized_signals,
            }
        )
    result = {
        "contract_version": "research-provenance/v1",
        "project_id": selection["project_id"],
        "snapshot_id": selection["snapshot_id"],
        "rule_set_hash": selection["rule_set_hash"],
        "candidate_space_hash": selection["candidate_space_hash"],
        "gate_report_hash": selection["gate_report_hash"],
        "selection_decision": {
            "seed_input": selection["seed_input"],
            "seed": selection["seed"],
            "selection_limit": selection["selection_limit"],
            "selected_count": selection["selected_count"],
            "selected_candidates": selection_refs,
        },
        "proposition_count": len(propositions),
        "propositions": propositions,
    }
    errors = validate_research_provenance(result, source)
    if errors:
        raise ValueError("\n".join(errors))
    return result


def _render(data: dict) -> bytes:
    return (canonical_json(data) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a reference-only v1.2 proposition provenance trace")
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION_PATH)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATE_PATH)
    parser.add_argument("--gates", type=Path, default=DEFAULT_GATE_PATH)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--rules", type=Path, default=TRANSFORMATION_RULE_CONFIG_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--check", action="store_true", help="compare generated bytes without writing")
    args = parser.parse_args()
    try:
        result = build_provenance(
            load_json(args.selection),
            load_json(args.candidates),
            load_json(args.gates),
            load_fixture(args.fixture),
            load_yaml(args.rules),
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rendered = _render(result)
    if args.check:
        try:
            observed = args.output.read_bytes()
        except OSError as exc:
            print(f"ERROR: {args.output}: {exc}; remediation: generate the provenance artifact first", file=sys.stderr)
            return 1
        if observed != rendered:
            print(f"ERROR: {args.output}: generated provenance bytes differ; remediation: regenerate the deterministic provenance artifact", file=sys.stderr)
            return 1
        changed = False
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        changed = args.output.exists() and args.output.read_bytes() == rendered
        if not changed:
            args.output.write_bytes(rendered)
    print(
        json.dumps(
            {"changed": not changed if not args.check else False, "command": "provenance", "proposition_count": result["proposition_count"], "status": "PASSED"},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
