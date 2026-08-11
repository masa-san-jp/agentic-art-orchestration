#!/usr/bin/env python3
"""Validate the v1.2 metadata-only research execution boundary."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from tools.validate import V12_BOUNDARY_CONFIG_PATH, load_yaml, validate_research_execution_boundary
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.validate import V12_BOUNDARY_CONFIG_PATH, load_yaml, validate_research_execution_boundary


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the v1.2 research execution boundary")
    parser.add_argument("--check", action="store_true", help="validate the checked-in boundary without writing")
    args = parser.parse_args()
    errors = validate_research_execution_boundary(
        load_yaml(V12_BOUNDARY_CONFIG_PATH),
        "config/research-execution-boundary.yaml",
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print('{"changed": false, "command": "v12-boundary", "status": "PASSED"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
