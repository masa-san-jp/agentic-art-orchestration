#!/usr/bin/env python3
"""Run the deterministic offline v1.2 research execution E2E."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

try:
    from tools.candidate_gates import build_gate_report
    from tools.candidate_selection import build_selection
    from tools.candidate_space import build_candidate_space, canonical_json, load_fixture
    from tools.child_quality_gates import run_child_quality_gates, sha256_hex
    from tools.interaction_e2e import run_interaction_e2e
    from tools.proposition_provenance import build_provenance
    from tools.validate import (
        ROOT,
        TRANSFORMATION_RULE_CONFIG_PATH,
        load_json,
        load_yaml,
        validate_child_quality_gates,
        validate_v12_e2e,
    )
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.candidate_gates import build_gate_report
    from tools.candidate_selection import build_selection
    from tools.candidate_space import build_candidate_space, canonical_json, load_fixture
    from tools.child_quality_gates import run_child_quality_gates, sha256_hex
    from tools.interaction_e2e import run_interaction_e2e
    from tools.proposition_provenance import build_provenance
    from tools.validate import ROOT, TRANSFORMATION_RULE_CONFIG_PATH, load_json, load_yaml, validate_child_quality_gates, validate_v12_e2e


DEFAULT_FIXTURE_DIR = ROOT / "tests/fixtures/v12-candidates"
DEFAULT_MANIFEST = ROOT / "config/repositories.yaml"
DEFAULT_WORKSPACE_ROOT = ROOT / "repos"
DEFAULT_OUTPUT = ROOT / "data/v12-e2e.json"


class V12E2EError(RuntimeError):
    """The v1.2 E2E did not prove a required invariant."""


def _validate_child_quality_gates_for_manifest(report: dict, manifest: dict, source: str) -> None:
    """Reject reused evidence that is not for this exact manifest and gate set."""
    errors = validate_child_quality_gates(report, source)
    if report.get("manifest_hash") != sha256_hex(manifest):
        errors.append("child quality gate manifest hash does not match the supplied manifest")
    expected = {
        repository.get("id"): repository
        for repository in manifest.get("repositories", [])
        if isinstance(repository, dict)
    }
    results = report.get("results", [])
    if {item.get("repository") for item in results if isinstance(item, dict)} != set(expected):
        errors.append("child quality gate repositories do not match the supplied manifest")
    for item in results:
        if not isinstance(item, dict):
            continue
        repository = expected.get(item.get("repository"))
        if repository is None:
            continue
        if item.get("observed_commit") != repository.get("observed_commit"):
            errors.append(f"child quality gate commit does not match repository {item.get('repository')!r}")
        if item.get("quality_gate_hash") != sha256_hex(repository.get("quality_gates", [])):
            errors.append(f"child quality gate definition does not match repository {item.get('repository')!r}")
        commands = [gate.get("command") for gate in item.get("gates", []) if isinstance(gate, dict)]
        if commands != repository.get("quality_gates"):
            errors.append(f"child quality gate commands do not match repository {item.get('repository')!r}")
    if errors:
        raise V12E2EError("provided child quality gate evidence is invalid: " + " | ".join(errors[:5]))


def _render(data: dict) -> bytes:
    return (canonical_json(data) + "\n").encode("utf-8")


def _deterministic_view(value: object) -> object:
    """Remove runtime-only gate output before comparing repeated runs."""
    if isinstance(value, dict):
        return {
            key: _deterministic_view(child)
            for key, child in value.items()
            if key not in {
                "duration_ms",
                "output_redacted",
                "output_sha256",
                "output_truncated",
            }
        }
    if isinstance(value, list):
        return [_deterministic_view(child) for child in value]
    return value


def _summary(
    candidate_space: dict,
    gate_report: dict,
    selection: dict,
    provenance: dict,
    child_gates: dict,
) -> dict:
    proposition = provenance["propositions"]
    return {
        "contract_version": provenance["contract_version"],
        "proposition_count": provenance["proposition_count"],
        "proposition_ids": [item["proposition_id"] for item in proposition],
        "signal_ids": sorted({trace["signal_id"] for item in proposition for trace in item["normalized_signals"]}),
        "source_commits": sorted({trace["source_commit"] for item in proposition for trace in item["normalized_signals"]}),
        "evidence_locators": sorted({locator for item in proposition for trace in item["normalized_signals"] for locator in trace["evidence_locators"]}),
    }


def run_v12_e2e(
    run_id: str = "V12-E2E-001:attempt-1",
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    manifest_path: Path = DEFAULT_MANIFEST,
    workspace_root: Path = DEFAULT_WORKSPACE_ROOT,
    child_quality_gates: dict | None = None,
) -> dict:
    """Execute all v1.2 stages in memory and summarize immutable evidence."""
    registry = load_yaml(TRANSFORMATION_RULE_CONFIG_PATH)
    signals = load_fixture(fixture_dir)
    manifest = load_yaml(manifest_path)
    candidate_space = build_candidate_space(copy.deepcopy(signals), copy.deepcopy(registry), "v12-e2e.candidates")
    gate_report = build_gate_report(candidate_space, copy.deepcopy(signals), copy.deepcopy(registry), "v12-e2e.gates")
    selection = build_selection(candidate_space, gate_report, "agentic-art-orchestration", "v12-e2e", 1, "v12-e2e.selection")
    provenance = build_provenance(selection, candidate_space, gate_report, copy.deepcopy(signals), copy.deepcopy(registry), "v12-e2e.provenance")
    if child_quality_gates is None:
        child_gates = run_child_quality_gates(manifest, workspace_root, run_id=f"{run_id}:child-gates")
    else:
        child_gates = copy.deepcopy(child_quality_gates)
        _validate_child_quality_gates_for_manifest(child_gates, manifest, f"{run_id}:child-quality-gates")
    first = {
        "candidate_space": copy.deepcopy(candidate_space),
        "gate_report": copy.deepcopy(gate_report),
        "selection": copy.deepcopy(selection),
        "provenance": copy.deepcopy(provenance),
        "child_gates": copy.deepcopy(child_gates),
    }
    second = {
        "candidate_space": build_candidate_space(copy.deepcopy(signals), copy.deepcopy(registry), "v12-e2e.candidates"),
        "gate_report": None,
        "selection": None,
        "provenance": None,
        "child_gates": copy.deepcopy(child_gates),
    }
    second["gate_report"] = build_gate_report(second["candidate_space"], copy.deepcopy(signals), copy.deepcopy(registry), "v12-e2e.gates")
    second["selection"] = build_selection(second["candidate_space"], second["gate_report"], "agentic-art-orchestration", "v12-e2e", 1, "v12-e2e.selection")
    second["provenance"] = build_provenance(second["selection"], second["candidate_space"], second["gate_report"], copy.deepcopy(signals), copy.deepcopy(registry), "v12-e2e.provenance")
    if _deterministic_view(first) != _deterministic_view(second):
        raise V12E2EError("repeated v1.2 pipeline evidence is not deterministic; remediation: remove nondeterministic inputs")
    interaction = run_interaction_e2e(f"{run_id}:v11-regression")
    v11_regression = {
        "interaction_contract": interaction["contract_version"],
        "artifact_policy": interaction["user_artifact_policy"],
        "raw_conversation_stored": interaction["interaction"]["raw_conversation_stored"],
        "remote_operations": interaction["remote_operations"],
        "acceptance": interaction["acceptance"],
    }
    output = {
        "contract_version": "v12-e2e/v1",
        "run_id": run_id,
        "network": "disabled",
        "pipeline": {
            "signal_count": len(signals),
            "rule_set_hash": candidate_space["rule_set_hash"],
            "snapshot_id": candidate_space["snapshot_id"],
            "candidate_count": candidate_space["candidate_count"],
            "gate_report_hash": selection["gate_report_hash"],
            "selection": {
                "seed": selection["seed"],
                "seed_input": selection["seed_input"],
                "selected_count": selection["selected_count"],
                "selected_candidate_ids": [item["candidate_id"] for item in selection["selected_candidates"]],
            },
            "provenance": _summary(candidate_space, gate_report, selection, provenance, child_gates),
        },
        "child_quality_gates": {
            "contract_version": child_gates["contract_version"],
            "repository_count": child_gates["repository_count"],
            "statuses": sorted({item["status"] for item in child_gates["results"]}),
            "workspace_states": sorted({item["workspace_state"] for item in child_gates["results"]}),
            "execution_modes": sorted({item["execution_mode"] for item in child_gates["results"]}),
        },
        "v11_regression": v11_regression,
        "acceptance": {
            "signals_to_provenance": provenance["proposition_count"] == selection["selected_count"] and set(_summary(candidate_space, gate_report, selection, provenance, child_gates)["signal_ids"]) == {signal["signal_id"] for signal in signals},
            "selection_deterministic": _deterministic_view(first) == _deterministic_view(second),
            "child_gates_observed": child_gates["repository_count"] == len(manifest["repositories"]),
            "v11_unchanged": v11_regression["interaction_contract"] == "interaction-e2e/v1" and v11_regression["artifact_policy"] == "CREATE_ONLY" and v11_regression["raw_conversation_stored"] is False,
            "no_child_mutation": all(item["workspace_state"] != "DIRTY" for item in child_gates["results"]),
            "no_remote_mutation": v11_regression["remote_operations"] == [],
        },
        "remote_operations": [],
    }
    errors = validate_v12_e2e(output, manifest, "v12-e2e")
    if errors:
        raise V12E2EError("\n".join(errors))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic offline v1.2 research E2E")
    parser.add_argument("--run-id", default="V12-E2E-001:attempt-1")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--child-quality-gates", type=Path, help="reuse one validated child-gate report for this parent-only E2E")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        child_quality_gates = None
        if args.child_quality_gates:
            child_quality_gates = json.loads(args.child_quality_gates.read_text(encoding="utf-8"))
        result = run_v12_e2e(args.run_id, args.fixture, args.manifest, args.workspace_root, child_quality_gates)
        rendered = _render(result)
        if args.check:
            if args.output.read_bytes() != rendered:
                raise V12E2EError("v1.2 E2E output is stale; remediation: regenerate v12-e2e.json")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(rendered)
    except (OSError, TypeError, ValueError, KeyError, V12E2EError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"changed": not args.check, "command": "v12-e2e", "network": result["network"], "selected_count": result["pipeline"]["selection"]["selected_count"], "status": "PASSED"}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
