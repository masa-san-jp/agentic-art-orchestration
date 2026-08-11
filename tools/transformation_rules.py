#!/usr/bin/env python3
"""Validate the finite, explicit v1.2 transformation-rule registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from tools.validate import TRANSFORMATION_RULE_CONFIG_PATH, load_yaml, validate_transformation_rule_registry
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.validate import TRANSFORMATION_RULE_CONFIG_PATH, load_yaml, validate_transformation_rule_registry


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the explicit v1.2 transformation-rule registry")
    parser.add_argument("--check", action="store_true", help="validate without writing")
    args = parser.parse_args()
    errors = validate_transformation_rule_registry(
        load_yaml(TRANSFORMATION_RULE_CONFIG_PATH),
        "config/transformation-rules.yaml",
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    rules = load_yaml(TRANSFORMATION_RULE_CONFIG_PATH).get("rules", [])
    print(
        json.dumps(
            {
                "changed": False,
                "command": "transformation-rules",
                "rule_count": len(rules),
                "status": "PASSED",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
