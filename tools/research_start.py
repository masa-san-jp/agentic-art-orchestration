#!/usr/bin/env python3
"""Run the parent input pipeline and dry-run acceptance at the Research boundary."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from tools.input_pipeline import run_input_pipeline
    from tools.research_request import build_research_request
    from tools.signal_bundle import load_json
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.input_pipeline import run_input_pipeline
    from tools.research_request import build_research_request
    from tools.signal_bundle import load_json


ROOT = Path(__file__).resolve().parents[1]


def _git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    commit = result.stdout.strip()
    if result.returncode != 0:
        raise ValueError("research-start: parent HEAD is unavailable; remediation: run inside a Git checkout")
    return commit


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _accept_dry_run(request_path: Path, research_root: Path, child_python: str) -> dict[str, Any]:
    acceptor = research_root / "tools" / "accept_research_request.py"
    if not acceptor.is_file():
        raise ValueError("research-start: Research acceptance CLI is missing; remediation: pin a Research checkout with the inbound request contract")
    result = subprocess.run(
        [child_python, str(acceptor), str(request_path), "--dry-run", "--root", str(research_root)],
        cwd=research_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(
            "research-start: Research request dry-run was rejected"
            f" ({detail[:500]}); remediation: inspect the pinned Research contract and request fields"
        )
    try:
        summary = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("research-start: Research acceptance returned non-JSON output; remediation: preserve the child acceptance summary contract") from exc
    if not isinstance(summary, dict) or summary.get("status") not in {"DRY_RUN", "ALREADY_APPLIED"}:
        raise ValueError("research-start: Research acceptance did not reach a terminal dry-run state; remediation: keep the boundary fail-closed")
    return summary


def run_research_start(
    bundle: dict[str, Any],
    *,
    project_id: str,
    seed_input: str,
    request_id: str,
    requested_at: str,
    project_slug: str,
    project_title: str | None,
    source_commit: str,
    research_root: Path,
    child_python: str | None = None,
) -> dict[str, Any]:
    resolved_child_python = child_python
    if resolved_child_python is None:
        child_venv = research_root / ".venv" / "bin" / "python"
        resolved_child_python = str(child_venv) if child_venv.is_file() else sys.executable
    pipeline = run_input_pipeline(bundle, project_id=project_id, seed_input=seed_input)
    request = build_research_request(
        pipeline["selection"],
        bundle,
        request_id=request_id,
        requested_at=requested_at,
        project_slug=project_slug,
        project_title=project_title,
        source_commit=source_commit,
    )
    return {
        "pipeline": pipeline,
        "request": request,
        "research_acceptance": {"status": "PENDING", "performed": False},
        "research_root": str(research_root),
        "source_commit": source_commit,
        "child_python": resolved_child_python,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--seed-input", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--requested-at", required=True)
    parser.add_argument("--project-slug", required=True)
    parser.add_argument("--project-title")
    parser.add_argument("--source-commit")
    parser.add_argument("--research-root", type=Path, required=True)
    parser.add_argument("--child-python")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        source_commit = args.source_commit or _git_commit(ROOT)
        result = run_research_start(
            load_json(args.bundle),
            project_id=args.project_id,
            seed_input=args.seed_input,
            request_id=args.request_id,
            requested_at=args.requested_at,
            project_slug=args.project_slug,
            project_title=args.project_title,
            source_commit=source_commit,
            research_root=args.research_root,
            child_python=args.child_python,
        )
        output = args.output_dir
        _write(output / "candidate-space.json", result["pipeline"]["candidate_space"])
        _write(output / "candidate-gates.json", result["pipeline"]["gate_report"])
        _write(output / "selection.json", result["pipeline"]["selection"])
        _write(output / "research-provenance.json", result["pipeline"]["provenance"])
        request_path = output / "research-request.yaml"
        import yaml

        request_path.write_text(yaml.safe_dump(result["request"], allow_unicode=True, sort_keys=False), encoding="utf-8")
        acceptance = _accept_dry_run(request_path, args.research_root, result["child_python"])
        summary = {
            "command": "research-start",
            "request_id": result["request"]["request_id"],
            "selected_count": result["pipeline"]["selection"]["selected_count"],
            "research_acceptance": acceptance,
            "status": "PASSED",
        }
        _write(output / "research-start.json", summary)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
