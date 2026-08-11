#!/usr/bin/env python3
"""Deterministic dependency and path-conflict scheduler."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

try:
    from tools.validate import validate_work_item
except ModuleNotFoundError:  # direct execution as `python3 tools/scheduler.py`
    sys.path.insert(0, str(ROOT))
    from tools.validate import validate_work_item


def _path_conflicts(left: str, right: str) -> bool:
    left = left.rstrip("/")
    right = right.rstrip("/")
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _items_conflict(left: dict, right: dict) -> bool:
    left_targets = set(left.get("target_repositories", []))
    right_targets = set(right.get("target_repositories", []))
    if not left_targets.intersection(right_targets):
        return False
    return any(
        _path_conflicts(left_path, right_path)
        for left_path in left.get("allowed_paths", [])
        for right_path in right.get("allowed_paths", [])
    )


def _reason(detail: str) -> dict:
    return {"reason": detail}


def schedule(work_items: list[dict], limit: int | None = None) -> dict:
    """Return selected IDs and explicit exclusion reasons without mutating input."""
    if not isinstance(work_items, list):
        raise ValueError("scheduler input must be a list")
    by_id: dict[str, dict] = {}
    duplicate_ids: set[str] = set()
    for item in work_items:
        item_id = item.get("id") if isinstance(item, dict) else None
        if item_id in by_id:
            duplicate_ids.add(item_id)
        else:
            by_id[item_id] = item

    selected: list[dict] = []
    excluded: list[dict] = []
    for item_id in sorted(by_id, key=lambda value: str(value)):
        item = by_id[item_id]
        reasons: list[str] = []
        if item_id in duplicate_ids:
            reasons.append("duplicate work item ID")
        validation_errors = validate_work_item(item, f"scheduler:{item_id}") if isinstance(item, dict) else ["item is not an object"]
        if validation_errors:
            reasons.append("invalid work item: " + validation_errors[0])
        if isinstance(item, dict) and item.get("terminal_state") != "READY":
            reasons.append(f"terminal_state is {item.get('terminal_state')!r}, not READY")

        if isinstance(item, dict):
            for dependency in item.get("depends_on", []):
                dependency_item = by_id.get(dependency)
                if dependency_item is None:
                    reasons.append(f"dependency {dependency!r} is missing")
                elif dependency_item.get("terminal_state") != "DONE":
                    reasons.append(
                        f"dependency {dependency!r} is {dependency_item.get('terminal_state')!r}, not DONE"
                    )

        if not reasons and limit is not None and len(selected) >= limit:
            reasons.append(f"selection limit {limit} reached")

        if not reasons and isinstance(item, dict):
            for prior in selected:
                if _items_conflict(item, prior):
                    reasons.append(f"allowed path conflict with selected {prior['id']!r}")
                    break
            if not reasons:
                for active in work_items:
                    if not isinstance(active, dict) or active.get("id") == item_id:
                        continue
                    active_state = active.get("terminal_state")
                    lease = active.get("lease", {})
                    if active_state == "IN_PROGRESS" or (
                        isinstance(lease, dict) and lease.get("status") == "held"
                    ):
                        if _items_conflict(item, active):
                            reasons.append(
                                f"allowed path conflict with active {active.get('id')!r}"
                            )
                            break

        if reasons:
            excluded.append({"id": item_id, "reasons": reasons})
        else:
            selected.append(item)

    return {
        "selected": [item["id"] for item in selected],
        "excluded": excluded,
        "considered": [item_id for item_id in sorted(by_id, key=lambda value: str(value))],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Select dependency-ready non-conflicting work items")
    parser.add_argument("--fixture", type=Path, required=True, help="YAML or JSON list/object fixture")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    fixture_path = args.fixture if args.fixture.is_absolute() else Path.cwd() / args.fixture
    with fixture_path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    work_items = payload.get("work_items", payload) if isinstance(payload, dict) else payload
    result = schedule(work_items, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
