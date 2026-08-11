#!/usr/bin/env python3
"""Evaluate deterministic specificity gates for research candidates."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

try:
    from tools.candidate_space import (
        DEFAULT_FIXTURE_DIR,
        DEFAULT_OUTPUT_PATH as DEFAULT_CANDIDATE_PATH,
        canonical_json,
        load_fixture,
    )
    from tools.validate import (
        ROOT,
        TRANSFORMATION_RULE_CONFIG_PATH,
        load_json,
        load_yaml,
        validate_candidate_gates,
        validate_candidate_space,
        validate_signal,
        validate_transformation_rule_registry,
    )
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.candidate_space import (
        DEFAULT_FIXTURE_DIR,
        DEFAULT_OUTPUT_PATH as DEFAULT_CANDIDATE_PATH,
        canonical_json,
        load_fixture,
    )
    from tools.validate import (
        ROOT,
        TRANSFORMATION_RULE_CONFIG_PATH,
        load_json,
        load_yaml,
        validate_candidate_gates,
        validate_candidate_space,
        validate_signal,
        validate_transformation_rule_registry,
    )


DEFAULT_OUTPUT_PATH = ROOT / "data/candidate-gates.json"
GATE_IDS = (
    "personal-specificity",
    "historical-specificity",
    "contemporary-specificity",
    "provenance",
    "genericness",
    "counterfactual",
)
SIGNAL_KINDS = ("self", "art-history", "marketing")


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _error(source: str, detail: str, remediation: str) -> str:
    return f"{source}: {detail}; remediation: {remediation}"


def _evidence(ref: dict) -> dict:
    return {
        key: copy.deepcopy(ref[key])
        for key in (
            "signal_id",
            "signal_kind",
            "attribute",
            "source_repository",
            "source_commit",
            "source_entity_ids",
            "source_locators",
            "evidence_locators",
        )
    }


def _all_evidence(candidate: dict) -> list[dict]:
    return [
        _evidence(ref)
        for kind in SIGNAL_KINDS
        for ref in candidate["inputs"][kind]
    ]


def _matching_evidence(candidate: dict, kind: str, attribute: str | None = None) -> list[dict]:
    return [
        _evidence(ref)
        for ref in candidate["inputs"][kind]
        if attribute is None or ref["attribute"] == attribute
    ]


def _gate(
    gate_id: str,
    passed: bool,
    evidence: list[dict],
    reason_code: str | None = None,
    details: dict | None = None,
) -> dict:
    result = {
        "gate_id": gate_id,
        "status": "PASS" if passed else "REJECT",
        "evidence": evidence or [],
        "reason_code": None if passed else reason_code,
    }
    if details:
        result["details"] = details
    return result


def _source_matches(signal: dict, ref: dict) -> bool:
    source = signal.get("source", {})
    return (
        ref.get("source_repository") == source.get("repository")
        and ref.get("source_commit") == source.get("commit")
        and ref.get("source_entity_ids") == source.get("entity_ids")
        and ref.get("source_locators") == source.get("locators")
        and ref.get("evidence_locators") == [item.get("locator") for item in signal.get("evidence_refs", [])]
    )


def evaluate_candidate(candidate: dict, signals: dict[str, dict], rule: dict, source: str = "candidate-gates") -> dict:
    """Return six explicit gate outcomes without generating proposition content."""
    composition = candidate["composition"]
    inputs = candidate["inputs"]

    def selected(slot_name: str) -> tuple[dict | None, dict | None]:
        slot = composition.get(slot_name, {})
        signal_id = slot.get("signal_id")
        return slot, signals.get(signal_id) if isinstance(signal_id, str) else None

    personal_slot, personal_signal = selected("personal_tension")
    personal_domain = personal_signal.get("domain", {}).get("self_model", {}) if personal_signal else {}
    personal_evidence = _matching_evidence(candidate, "self", "tensions")
    personal_pass = bool(
        personal_signal
        and personal_slot.get("signal_kind") == "self"
        and personal_slot.get("attribute") == "tensions"
        and personal_signal.get("signal_kind") == "self"
        and personal_signal.get("validity", {}).get("status") == "valid"
        and personal_domain.get("export_permitted") is True
        and personal_domain.get("consent_scope")
        and personal_domain.get("tensions")
    )

    historical_slot, historical_signal = selected("historical_operation")
    historical_domain = historical_signal.get("domain", {}).get("art_history", {}) if historical_signal else {}
    historical_evidence = _matching_evidence(candidate, "art-history", "relations")
    relations = historical_domain.get("relations", [])
    historical_pass = bool(
        historical_signal
        and historical_slot.get("signal_kind") == "art-history"
        and historical_slot.get("attribute") == "relations"
        and historical_signal.get("signal_kind") == "art-history"
        and historical_signal.get("validity", {}).get("status") == "valid"
        and historical_domain.get("canonical_graph_locator")
        and relations
        and all(isinstance(relation, dict) and relation.get("evidence_refs") for relation in relations)
    )

    contemporary_slot, contemporary_signal = selected("contemporary_condition")
    contemporary_domain = contemporary_signal.get("domain", {}).get("marketing", {}) if contemporary_signal else {}
    contemporary_evidence = _matching_evidence(candidate, "marketing", "stage")
    contemporary_pass = bool(
        contemporary_signal
        and contemporary_slot.get("signal_kind") == "marketing"
        and contemporary_slot.get("attribute") == "stage"
        and contemporary_signal.get("signal_kind") == "marketing"
        and contemporary_signal.get("validity", {}).get("status") == "valid"
        and contemporary_signal.get("freshness", {}).get("status") == "current"
        and contemporary_domain.get("stage")
        and contemporary_domain.get("freshness") == "current"
        and contemporary_domain.get("expires_at")
    )

    provenance_evidence = _all_evidence(candidate)
    matched_sources = sum(
        1
        for kind in SIGNAL_KINDS
        for ref in inputs[kind]
        if isinstance(signals.get(ref.get("signal_id")), dict) and _source_matches(signals[ref["signal_id"]], ref)
    )
    provenance_pass = matched_sources == sum(len(inputs[kind]) for kind in SIGNAL_KINDS)

    composition_ids = [slot.get("signal_id") for slot in composition.values()]
    composition_kinds = [slot.get("signal_kind") for slot in composition.values()]
    generic_pass = (
        len(composition_ids) == len(set(composition_ids)) == 3
        and set(composition_kinds) == set(rule["required_signal_kinds"])
        and all(isinstance(slot.get("attribute"), str) and slot["attribute"] for slot in composition.values())
    )

    required_kinds = set(rule["required_signal_kinds"])
    counterfactual_pass = (
        set(composition_kinds) == required_kinds
        and all(inputs.get(kind) for kind in required_kinds)
        and all(
            any(ref.get("signal_id") == composition[slot_name].get("signal_id") for ref in inputs[kind])
            for slot_name, slot in rule["composition"]["slots"].items()
            for kind in [slot["signal_kind"]]
        )
    )
    counterfactual_evidence = _all_evidence(candidate)

    gates = [
        _gate("personal-specificity", personal_pass, personal_evidence, "missing-personal-signal"),
        _gate("historical-specificity", historical_pass, historical_evidence, "missing-historical-signal"),
        _gate("contemporary-specificity", contemporary_pass, contemporary_evidence, "missing-contemporary-signal"),
        _gate("provenance", provenance_pass, provenance_evidence, "missing-provenance", {"matched_source_count": matched_sources}),
        _gate("genericness", generic_pass, _all_evidence(candidate), "generic-candidate", {"distinct_signal_count": len(set(composition_ids))}),
        _gate(
            "counterfactual",
            counterfactual_pass,
            counterfactual_evidence,
            "counterfactual-failure",
            {
                "required_signal_kinds": sorted(required_kinds),
                "observed_signal_kinds": sorted(set(composition_kinds)),
                "expected_rejection": "missing-required-signal",
            },
        ),
    ]
    result = {
        "candidate_id": candidate["candidate_id"],
        "overall_status": "PASS" if all(gate["status"] == "PASS" for gate in gates) else "REJECT",
        "gates": gates,
    }
    errors = validate_candidate_gates(
        {"contract_version": "research-candidate-gates/v1", "candidate_space_hash": "0" * 64, "evaluations": [result]},
        source,
    )
    if errors:
        raise ValueError("\n".join(errors))
    return result


def build_gate_report(candidate_space: dict, signals: list[dict], registry: dict, source: str = "candidate-gates") -> dict:
    candidate_errors = validate_candidate_space(candidate_space, f"{source}.candidates")
    if candidate_errors:
        raise ValueError("\n".join(candidate_errors))
    registry_errors = validate_transformation_rule_registry(registry, f"{source}.rules")
    if registry_errors:
        raise ValueError("\n".join(registry_errors))
    signal_by_id: dict[str, dict] = {}
    for index, signal in enumerate(signals):
        signal_errors = validate_signal(signal, f"{source}.signals[{index}]")
        if signal_errors:
            raise ValueError("\n".join(signal_errors))
        if signal["signal_id"] in signal_by_id:
            raise ValueError(_error(source, f"duplicate signal_id {signal['signal_id']!r}", "provide one signal per stable ID"))
        signal_by_id[signal["signal_id"]] = signal
    rules = {rule["rule_id"]: rule for rule in registry["rules"] if rule.get("status") == "active"}
    evaluations = []
    for candidate in candidate_space["candidates"]:
        rule = rules.get(candidate["rule_id"])
        if rule is None:
            raise ValueError(_error(source, f"candidate references unknown active rule {candidate['rule_id']!r}", "use a validated active transformation rule"))
        evaluations.append(evaluate_candidate(candidate, signal_by_id, rule, source))
    report = {
        "contract_version": "research-candidate-gates/v1",
        "candidate_space_hash": sha256_hex(candidate_space),
        "evaluations": evaluations,
    }
    errors = validate_candidate_gates(report, source)
    if errors:
        raise ValueError("\n".join(errors))
    return report


def _render(data: dict) -> bytes:
    return (canonical_json(data) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate deterministic specificity gates for v1.2 candidates")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATE_PATH)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--rules", type=Path, default=TRANSFORMATION_RULE_CONFIG_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--check", action="store_true", help="compare generated bytes without writing")
    args = parser.parse_args()
    try:
        report = build_gate_report(load_json(args.candidates), load_fixture(args.fixture), load_yaml(args.rules))
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rendered = _render(report)
    if args.check:
        try:
            observed = args.output.read_bytes()
        except OSError as exc:
            print(f"ERROR: {args.output}: {exc}; remediation: generate the gate artifact first", file=sys.stderr)
            return 1
        if observed != rendered:
            print(f"ERROR: {args.output}: generated gate bytes differ; remediation: regenerate the deterministic artifact", file=sys.stderr)
            return 1
        changed = False
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        changed = args.output.exists() and args.output.read_bytes() == rendered
        if not changed:
            args.output.write_bytes(rendered)
    print(
        json.dumps(
            {
                "changed": not changed if not args.check else False,
                "command": "candidate-gates",
                "evaluation_count": len(report["evaluations"]),
                "status": "PASSED",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
