#!/usr/bin/env python3
"""Materialize or check the deterministic networkless Drive live plan."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.drive_live_bridge import DriveLiveBridge, DriveLiveError, FakeDriveLiveProvider, GoogleDriveProvider  # noqa: E402
from tools.validate import load_json, load_yaml  # noqa: E402


DEFAULT_OUTPUT = ROOT / "data/drive-live-evidence.json"
METADATA_PATH = ROOT / "tests/fixtures/drive/create_metadata.json"


def _content() -> str:
    return "synthetic Drive live plan content; never committed to the evidence envelope"


def _write_or_check(result: dict, output: Path, check: bool) -> None:
    content = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != content:
            raise DriveLiveError("drive live plan is missing or stale; remediation: run without --check to materialize the deterministic plan")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute an approved-folder create/read Drive operation")
    parser.add_argument("--plan", action="store_true", help="run the networkless plan")
    parser.add_argument("--live", action="store_true", help="run one explicitly confirmed approved-folder CREATE/read check")
    parser.add_argument("--confirm-live", action="store_true", help="confirm the external CREATE/read operation")
    parser.add_argument("--fixture", action="store_true", help="use the networkless live provider")
    parser.add_argument("--folder-id")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.plan and args.live:
            raise DriveLiveError("--plan and --live cannot be combined; remediation: select one mode")
        mode = "live" if args.live else "plan"
        policy = load_yaml(ROOT / "config/drive-live-policy.yaml")
        approved = policy["approved_folder"]
        if mode == "live" and not args.confirm_live:
            raise DriveLiveError("live mode requires --confirm-live; remediation: keep plan mode unless a sandbox CREATE is explicitly authorized")
        provider = None
        folder_id = args.folder_id
        if mode == "live":
            if args.fixture:
                provider = FakeDriveLiveProvider()
                folder_id = folder_id or approved["fixture_id"]
            else:
                configured_folder = os.environ.get(approved["id_env_var"], "")
                if folder_id and folder_id != configured_folder:
                    raise DriveLiveError("folder ID does not match the approved environment value; remediation: use only the configured sandbox folder")
                folder_id = configured_folder
                if not folder_id:
                    raise DriveLiveError(f"live mode requires {approved['id_env_var']}; remediation: set it without committing the value")
                provider = GoogleDriveProvider(os.environ.get(policy["credential_env_var"], ""))
        metadata = load_json(METADATA_PATH)
        result = DriveLiveBridge(provider).create(
            content=_content(),
            metadata=metadata,
            idempotency_key="interaction:drive-live:fixture-001",
            mode=mode,
            folder_id=folder_id,
            run_id="DRIVE-LIVE-001:attempt-1",
            confirm_live=args.confirm_live,
        )
        _write_or_check(result, args.output.resolve(), args.check)
        print(json.dumps({"command": "drive-live-check", "changed": not args.check, "mode": mode, "status": result["status"], "remote_operation_count": len(result["remote_operations"])}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
