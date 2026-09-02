#!/usr/bin/env python3
"""Run the input knowledge bases' exporters and normalize what they hand over.

    python3 tools/ingest_signals.py --purpose artistic-research

Until now the adapters were called only from tests, so nothing carried a
knowledge base's records into the candidate space. This runs each declared input
repository's exporter, checks the envelope, translates every record through the
adapter for its kind, and writes what `tools/candidate_space.py` reads.

A record that fails its adapter stops the whole ingest. Composing a proposition
from a partial set would hide which knowledge was missing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    from tools.adapters import (
        AdapterError,
        adapt_art_history_signal,
        adapt_marketing_signal,
        adapt_self_model_signal,
        adapt_viewer_response_signal,
    )
    from tools.validate import load_yaml, validate_signal, validate_signal_export
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.adapters import (
        AdapterError,
        adapt_art_history_signal,
        adapt_marketing_signal,
        adapt_self_model_signal,
        adapt_viewer_response_signal,
    )
    from tools.validate import load_yaml, validate_signal, validate_signal_export

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/repositories.yaml"
DEFAULT_OUTPUT = ROOT / "data/signals"

ADAPTERS = {
    "self-model": adapt_self_model_signal,
    "art-history": adapt_art_history_signal,
    "marketing-trends": adapt_marketing_signal,
    "viewer-response-notes": adapt_viewer_response_signal,
}
GENERIC_SIGNAL_REPOSITORIES = {"self-model", "art-history", "marketing-trends"}


class IngestError(RuntimeError):
    """An input repository could not be read, or handed over something unusable."""


def _export(repository: dict, workspace_root: Path, purpose: str, python: str) -> dict:
    checkout = workspace_root / repository["path"]
    exporter = checkout / "tools/export_signals.py"
    if not exporter.is_file():
        raise IngestError(f"{repository['id']} has no tools/export_signals.py at {checkout}")
    result = subprocess.run(
        [python, "tools/export_signals.py", "--purpose", purpose],
        cwd=checkout, capture_output=True, text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1:] or ["no stderr"]
        raise IngestError(f"{repository['id']} export failed: {detail[0]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise IngestError(f"{repository['id']} export is not JSON: {exc}") from exc


def _observed_head(checkout: Path) -> str | None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True, text=True)
    return head.stdout.strip() if head.returncode == 0 else None


def ingest(workspace_root: Path, output: Path, purpose: str, python: str) -> dict:
    manifest = load_yaml(MANIFEST)
    inputs = [item for item in manifest["repositories"] if item.get("role") == "input-kb"]
    normalized: list[dict] = []
    warnings: list[str] = []
    deferred_boundaries: list[dict[str, str]] = []

    for repository in inputs:
        identifier = repository["id"]
        adapter = ADAPTERS.get(identifier)
        if adapter is None:
            raise IngestError(f"{identifier} is declared as an input but has no adapter")
        if identifier not in GENERIC_SIGNAL_REPOSITORIES:
            deferred_boundaries.append({
                "repository": identifier,
                "status": "SEPARATE_BOUNDARY",
                "route": "tools/viewer_response_gate.py",
            })
            continue

        payload = _export(repository, workspace_root, purpose, python)
        errors = validate_signal_export(payload, identifier)
        if errors:
            raise IngestError(f"{identifier} envelope is invalid: {errors[0]}")

        # The pin is what the exchange is qualified against, so a drift is worth
        # saying out loud. It does not stop an ingest: reading is not qualifying.
        head = _observed_head(workspace_root / repository["path"])
        if head and head != repository.get("observed_commit"):
            warnings.append(f"{identifier} is at {head[:8]}, manifest pin is {str(repository.get('observed_commit'))[:8]}")

        for record in payload["signals"]:
            try:
                signal = adapter(record)
            except AdapterError as exc:
                raise IngestError(f"{identifier} record {record.get('signal_id')!r} failed its adapter: {exc}") from exc
            signal_errors = validate_signal(signal, f"{identifier}:{signal['signal_id']}")
            if signal_errors:
                raise IngestError(f"{identifier} record {signal['signal_id']!r} is invalid after adapting: {signal_errors[0]}")
            normalized.append(signal)

    output.mkdir(parents=True, exist_ok=True)
    signal_files: list[str] = []
    for signal in normalized:
        relative = Path(signal["source"]["repository"]) / f"{signal['signal_id'].replace(':', '_')}.json"
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(signal, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        signal_files.append(str(relative))

    portfolio = {"version": 1, "signal_files": sorted(signal_files), "requirements": []}
    (output / "portfolio.json").write_text(
        json.dumps(portfolio, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "status": "PASSED",
        "signal_count": len(normalized),
        "by_kind": {kind: sum(1 for s in normalized if s["signal_kind"] == kind) for kind in sorted({s["signal_kind"] for s in normalized})},
        "portfolio": str(output / "portfolio.json"),
        "warnings": warnings,
        "deferred_boundaries": deferred_boundaries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purpose", required=True)
    parser.add_argument("--workspace-root", type=Path, default=ROOT / "repos")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--child-python", default=sys.executable)
    args = parser.parse_args(argv)
    try:
        report = ingest(args.workspace_root, args.output, args.purpose, args.child_python)
    except (IngestError, OSError, KeyError) as exc:
        print(json.dumps({"status": "FAILED", "detail": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
