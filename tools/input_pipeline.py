#!/usr/bin/env python3
"""Run the real input-KB bundle through consumer, candidate, gate, and selection stages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from tools.candidate_gates import build_gate_report
    from tools.candidate_space import build_candidate_space
    from tools.candidate_selection import build_selection
    from tools.consumer import import_signals
    from tools.proposition_provenance import build_provenance
    from tools.signal_bundle import validate_signal_bundle
    from tools.validate import load_yaml
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.candidate_gates import build_gate_report
    from tools.candidate_space import build_candidate_space
    from tools.candidate_selection import build_selection
    from tools.consumer import import_signals
    from tools.proposition_provenance import build_provenance
    from tools.signal_bundle import validate_signal_bundle
    from tools.validate import load_yaml


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def run_input_pipeline(
    bundle: dict[str, Any],
    *,
    project_id: str,
    seed_input: str,
    selection_limit: int = 1,
    rules: dict[str, Any] | None = None,
    inspiration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors = validate_signal_bundle(bundle)
    if errors:
        raise ValueError("\n".join(errors))
    signals = bundle["records"]
    # The consumer call is intentional: candidate generation receives the same
    # validated records, while this call proves the consumer boundary was used.
    imported = import_signals(signals)
    registry = rules if rules is not None else load_yaml(ROOT / "config/transformation-rules.yaml")
    candidate_space = build_candidate_space(signals, registry, "input-pipeline.candidates")
    gate_report = build_gate_report(candidate_space, signals, registry, "input-pipeline.gates")
    selection = build_selection(candidate_space, gate_report, project_id, seed_input, selection_limit, "input-pipeline.selection")
    provenance = build_provenance(selection, candidate_space, gate_report, signals, registry, "input-pipeline.provenance")
    result = {
        "bundle": bundle,
        "consumer_package": imported,
        "candidate_space": candidate_space,
        "gate_report": gate_report,
        "selection": selection,
        "provenance": provenance,
    }
    if inspiration is not None:
        from tools.inspiration import settle_inspiration

        result["inspiration"] = settle_inspiration(inspiration, result)
    return result


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--seed-input", required=True)
    parser.add_argument("--selection-limit", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_input_pipeline(_load_json(args.bundle), project_id=args.project_id, seed_input=args.seed_input, selection_limit=args.selection_limit)
        output = args.output_dir
        _write(output / "candidate-space.json", result["candidate_space"])
        _write(output / "candidate-gates.json", result["gate_report"])
        _write(output / "selection.json", result["selection"])
        _write(output / "research-provenance.json", result["provenance"])
        print(json.dumps({"command": "input-pipeline", "selected_count": result["selection"]["selected_count"], "status": "PASSED"}, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
