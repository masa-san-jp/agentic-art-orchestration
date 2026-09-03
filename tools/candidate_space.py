#!/usr/bin/env python3
"""Generate a deterministic, provenance-preserving v1.2 candidate space."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path

try:
    from tools.validate import (
        ROOT,
        TRANSFORMATION_RULE_CONFIG_PATH,
        load_json,
        load_yaml,
        validate_candidate_space,
        validate_signal,
        validate_transformation_rule_registry,
    )
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.validate import (
        ROOT,
        TRANSFORMATION_RULE_CONFIG_PATH,
        load_json,
        load_yaml,
        validate_candidate_space,
        validate_signal,
        validate_transformation_rule_registry,
    )


SIGNAL_KINDS = ("self", "art-history", "marketing")
PERSONAL_ANCHOR_ATTRIBUTES = ("tensions", "recurring_patterns")
DEFAULT_FIXTURE_DIR = ROOT / "tests/fixtures/v12-candidates"
DEFAULT_OUTPUT_PATH = ROOT / "data/candidate-space.json"


def canonical_json(value: object) -> str:
    """Return the byte-level canonical representation used for all hashes."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def personal_anchor_id(signal_id: str, attribute: str, value: object) -> str:
    """Return the stable opaque identity for one consented self-model anchor."""
    payload = f"{signal_id}\n{attribute}\n{canonical_json(value)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _error(source: str, detail: str, remediation: str) -> str:
    return f"{source}: {detail}; remediation: {remediation}"


def load_fixture(fixture_dir: Path) -> list[dict]:
    """Load signals from a small portfolio manifest without copying child data."""
    portfolio_path = fixture_dir / "portfolio.json"
    portfolio = load_json(portfolio_path)
    if not isinstance(portfolio, dict) or not isinstance(portfolio.get("signal_files"), list):
        raise ValueError(_error(str(portfolio_path), "signal_files must be a list", "declare fixture signal files"))
    signals: list[dict] = []
    fixture_root = fixture_dir.resolve().parent
    for relative_path in portfolio["signal_files"]:
        if not isinstance(relative_path, str):
            raise ValueError(_error(str(portfolio_path), "signal file path must be a string", "use a relative JSON path"))
        path = (fixture_dir / relative_path).resolve()
        if fixture_root not in path.parents:
            raise ValueError(_error(str(portfolio_path), f"unsafe signal path {relative_path!r}", "keep fixture inputs inside the fixture collection"))
        signal = load_json(path)
        if not isinstance(signal, dict):
            raise ValueError(_error(str(path), "signal must be an object", "provide a normalized signal object"))
        signals.append(signal)
    return signals


def _validated_signals(signals: list[dict], source: str) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for index, signal in enumerate(signals):
        errors = validate_signal(signal, f"{source}[{index}]")
        if errors:
            raise ValueError("\n".join(errors))
        signal_id = signal["signal_id"]
        if signal_id in by_id:
            raise ValueError(_error(source, f"duplicate signal_id {signal_id!r}", "provide one immutable signal per ID"))
        by_id[signal_id] = signal
    return by_id


def _input_ref(signal: dict, attribute: str) -> dict:
    source = signal["source"]
    return {
        "signal_id": signal["signal_id"],
        "signal_kind": signal["signal_kind"],
        "attribute": attribute,
        "source_repository": source["repository"],
        "source_commit": source["commit"],
        "source_entity_ids": list(source["entity_ids"]),
        "source_locators": list(source["locators"]),
        "evidence_locators": [ref["locator"] for ref in signal["evidence_refs"]],
    }


def _personal_anchor_options(signal: dict) -> list[dict]:
    """Enumerate only valid, export-permitted self-model values as opaque options."""
    if (
        signal.get("signal_kind") != "self"
        or signal.get("validity", {}).get("status") != "valid"
    ):
        return []
    domain = signal.get("domain", {}).get("self_model", {})
    if domain.get("export_permitted") is not True or not domain.get("consent_scope"):
        return []
    options: list[dict] = []
    for attribute in PERSONAL_ANCHOR_ATTRIBUTES:
        values = domain.get(attribute)
        if not isinstance(values, list):
            continue
        for value in sorted(values, key=canonical_json):
            if not isinstance(value, str) or not value.strip():
                continue
            options.append(
                {
                    "anchor_id": personal_anchor_id(signal["signal_id"], attribute, value),
                    "attribute": attribute,
                    "signal": signal,
                }
            )
    return sorted(options, key=lambda option: option["anchor_id"])


def eligible_personal_anchors(signals: list[dict], source: str = "self-diversity") -> list[dict]:
    """Return stable anchor metadata without returning the underlying self facts."""
    signal_by_id = _validated_signals(signals, f"{source}.signals")
    anchors: list[dict] = []
    for signal_id in sorted(signal_by_id):
        for option in _personal_anchor_options(signal_by_id[signal_id]):
            anchors.append(
                {
                    "anchor_id": option["anchor_id"],
                    "attribute": option["attribute"],
                    "signal_id": signal_id,
                }
            )
    seen: set[str] = set()
    unique: list[dict] = []
    for anchor in sorted(anchors, key=lambda item: item["anchor_id"]):
        if anchor["anchor_id"] in seen:
            continue
        seen.add(anchor["anchor_id"])
        unique.append(anchor)
    return unique


def _candidate(rule: dict, selected: dict[str, dict], snapshot_id: str, personal_anchor: dict | None = None) -> dict:
    bindings = rule["attribute_bindings"]
    inputs = {
        kind: [_input_ref(selected[kind], attribute) for attribute in sorted(bindings[kind])]
        for kind in SIGNAL_KINDS
    }
    composition = {
        slot_name: {
            "signal_id": selected[slot["signal_kind"]]["signal_id"],
            "signal_kind": slot["signal_kind"],
            "attribute": (
                personal_anchor["attribute"]
                if slot_name == "personal_tension" and personal_anchor is not None
                else slot["attribute"]
            ),
        }
        for slot_name, slot in sorted(rule["composition"]["slots"].items())
    }
    identity = {
        "rule_id": rule["rule_id"],
        "snapshot_id": snapshot_id,
        "signal_ids": {kind: selected[kind]["signal_id"] for kind in SIGNAL_KINDS},
    }
    if personal_anchor is not None:
        identity["personal_anchor_id"] = personal_anchor["anchor_id"]
    candidate = {
        "candidate_id": f"candidate:{sha256_hex(identity)[:16]}",
        "rule_id": rule["rule_id"],
        "inputs": inputs,
        "composition": composition,
    }
    if rule["composition"].get("composition_mode") is not None:
        candidate["composition_mode"] = rule["composition"]["composition_mode"]
    return candidate


def build_candidate_space(signals: list[dict], registry: dict, source: str = "candidate-space") -> dict:
    """Enumerate all finite rule/input combinations in canonical order."""
    signal_by_id = _validated_signals(signals, f"{source}.signals")
    rule_errors = validate_transformation_rule_registry(registry, f"{source}.rules")
    if rule_errors:
        raise ValueError("\n".join(rule_errors))

    normalized_signals = [signal_by_id[signal_id] for signal_id in sorted(signal_by_id)]
    snapshot_id = sha256_hex(normalized_signals)
    rule_set_hash = sha256_hex(registry)
    by_kind: dict[str, list[dict]] = {kind: [] for kind in SIGNAL_KINDS}
    for signal in normalized_signals:
        by_kind[signal["signal_kind"]].append(signal)

    candidates: list[dict] = []
    active_rules = sorted(
        (rule for rule in registry["rules"] if rule.get("status") == "active"),
        key=lambda rule: rule["rule_id"],
    )
    for rule in active_rules:
        required_kinds = rule["required_signal_kinds"]
        missing = sorted(kind for kind in required_kinds if not by_kind.get(kind))
        if missing:
            raise ValueError(
                _error(
                    source,
                    f"rule {rule['rule_id']!r} has missing-required-signal kinds {missing!r}",
                    "provide a validated signal for every required kind or reject the snapshot",
                )
            )
        uses_personal_anchors = any(
            slot.get("signal_kind") == "self"
            and slot.get("attribute") in PERSONAL_ANCHOR_ATTRIBUTES
            for slot in rule["composition"]["slots"].values()
        )
        eligible_anchor_total = sum(len(_personal_anchor_options(signal)) for signal in by_kind["self"])
        uses_personal_anchors = uses_personal_anchors and eligible_anchor_total >= 1
        if uses_personal_anchors:
            self_options: list[tuple[dict, dict | None]] = []
            for signal in sorted(by_kind["self"], key=lambda item: item["signal_id"]):
                options = _personal_anchor_options(signal)
                self_options.extend((option["signal"], option) for option in options)
                if not options:
                    self_options.append((signal, None))
            ordered_groups = [
                self_options,
                *[sorted(by_kind[kind], key=lambda signal: signal["signal_id"]) for kind in SIGNAL_KINDS[1:]],
            ]
        else:
            ordered_groups = [sorted(by_kind[kind], key=lambda signal: signal["signal_id"]) for kind in SIGNAL_KINDS]
        for combination in itertools.product(*ordered_groups):
            if uses_personal_anchors:
                self_signal, personal_anchor = combination[0]
                selected = {
                    "self": self_signal,
                    **{signal["signal_kind"]: signal for signal in combination[1:]},
                }
            else:
                personal_anchor = None
                selected = {signal["signal_kind"]: signal for signal in combination}
            candidates.append(_candidate(rule, selected, snapshot_id, personal_anchor))

    candidates.sort(key=lambda item: item["candidate_id"])
    result = {
        "contract_version": "research-candidate/v1",
        "snapshot_id": snapshot_id,
        "rule_set_hash": rule_set_hash,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    errors = validate_candidate_space(result, source)
    if errors:
        raise ValueError("\n".join(errors))
    return result


def _render(data: dict) -> bytes:
    return (canonical_json(data) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the deterministic v1.2 candidate space")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--rules", type=Path, default=TRANSFORMATION_RULE_CONFIG_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--check", action="store_true", help="compare the generated bytes without writing")
    args = parser.parse_args()

    try:
        result = build_candidate_space(load_fixture(args.fixture), load_yaml(args.rules))
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rendered = _render(result)
    if args.check:
        try:
            observed = args.output.read_bytes()
        except OSError as exc:
            print(f"ERROR: {args.output}: {exc}; remediation: generate the candidate artifact first", file=sys.stderr)
            return 1
        if observed != rendered:
            print(f"ERROR: {args.output}: generated candidate bytes differ; remediation: regenerate the deterministic artifact", file=sys.stderr)
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
                "command": "candidate-space",
                "candidate_count": result["candidate_count"],
                "status": "PASSED",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
