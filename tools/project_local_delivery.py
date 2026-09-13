#!/usr/bin/env python3
"""Verify and finalize a Project-local plan delivery.

The Project checkout remains the authority for receiver validation.  This
adapter only supplies the delivery receipt and advances an already-projected
cycle after the native Project checks have passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.delivery_completion import completion


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def read(path: Path) -> object:
    if path.is_symlink() or not path.is_absolute() or path.resolve() != path:
        raise ValueError("EXPLICIT_NONSYMLINK_PATH_REQUIRED")
    return json.loads(path.read_bytes())


def _child_check_script() -> str:
    # This code deliberately imports the Project checkout's native modules.
    # It does not reproduce Project schemas or receiver rules in the parent.
    return r'''
import hashlib, json, subprocess, sys
from pathlib import Path
from tools import catalog_lineage, catalog_sync
from tools.attestation_receiver import check_envelope
from tools.validate import mapping_fields, validate, validate_record

root = Path(sys.argv[1]).resolve()
expected = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if not isinstance(expected, list) or not expected:
    raise ValueError("DELIVERY_EXPECTATION_REQUIRED")
rows = catalog_sync._parse_list_records(root / "plans/index.yaml", "records")
by_id = {row["id"]: row for row in rows}
index = catalog_lineage.index_document(root)
indexed = {item.get("record_id", item.get("lineage", {}).get("record_id")): item
           for item in index["records"]}
errors = list(validate(root))
records = []
for wanted in expected:
    if not isinstance(wanted, dict) or set(wanted) != {"record_id", "content_sha256", "creator_id", "origin_instance_id", "source_identity"}:
        raise ValueError("DELIVERY_EXPECTATION_CONTRACT")
    record_id = wanted["record_id"]
    row = by_id.get(record_id)
    if row is None:
        errors.append(record_id + ": RECORD_NOT_FOUND")
        continue
    errors.extend(validate_record(root, row))
    item = indexed.get(record_id, {})
    if item.get("status") != "VALIDATED":
        errors.append(record_id + ": LINEAGE_NOT_VALIDATED")
        continue
    metadata = mapping_fields(root / row["path"] / "metadata.yaml")
    attestation = check_envelope(root / row["path"], metadata, row,
                                 producer_repository="masa-san-jp/agentic-art-production")
    lineage = item["lineage"]
    actual = {key: row.get("content_sha256") if key == "content_sha256" else
              lineage.get(key) if key in {"creator_id", "origin_instance_id", "source_identity"} else record_id
              for key in ("record_id", "content_sha256", "creator_id", "origin_instance_id", "source_identity")}
    if actual != wanted:
        errors.append(record_id + ": DELIVERY_EXPECTATION_MISMATCH")
    records.append({
        "record_id": record_id,
        "path": row["path"],
        "content_sha256": hashlib.sha256((root / row["path"] / "plan.md").read_bytes()).hexdigest(),
        "lineage_sha256": hashlib.sha256((root / row["path"] / "lineage.json").read_bytes()).hexdigest(),
        "attestation_sha256": hashlib.sha256((root / row["path"] / "public-plan-attestation.json").read_bytes()).hexdigest(),
        "creator_id": lineage["creator_id"],
        "origin_instance_id": lineage["origin_instance_id"],
        "source_identity": lineage["source_identity"],
        "canonical_revision": lineage["canonical_revision"],
        "attestation_contract": attestation["contract_version"],
    })
if errors:
    print(json.dumps({"status": "BLOCKED", "errors": sorted(set(errors)), "records": records}, ensure_ascii=False))
    raise SystemExit(2)
head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
status = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"], text=True).splitlines()
blockers = [{"record_id": item.get("record_id"), "status": item.get("status")}
            for item in index["records"] if item.get("status") not in {"VALIDATED"}]
for blocker in blockers:
    if blocker["record_id"] is None:
        blocker["record_id"] = next((item.get("lineage", {}).get("record_id") for item in index["records"]
                                      if item.get("status") == blocker["status"] and item.get("lineage")), None)
print(json.dumps({
    "status": "VERIFIED",
    "records": records,
    "existing_blockers": blockers,
    "target_git": {"head": head, "working_tree": "OUTPUT_ONLY_UNCOMMITTED" if status else "CLEAN", "remote_sync": "NOT_RUN"},
    "checks": {"project_validator": "PASS", "production_attestation": "PASS", "lineage": "PASS", "catalog_sync": "PASS", "private_workspace": "PASS"},
}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
'''


def prepare_lineage(project_code: Path, python: str, root: Path, record_id: str,
                    instance_profile: Path, lineage_output: Path,
                    profile_output: Path) -> None:
    """Ask the Project code to build the closed input for a new record."""
    profile = read(instance_profile)
    permissions = profile.get("permissions") if isinstance(profile, dict) else None
    if (not isinstance(profile, dict) or not isinstance(profile.get("instance_id"), str)
            or not isinstance(profile.get("creator_id"), str) or not isinstance(permissions, dict)):
        raise ValueError("INSTANCE_PROFILE_REQUIRED")
    script = r'''
import sys
from pathlib import Path
from tools import catalog_lineage

root = Path(sys.argv[1]).resolve()
record_id, instance_id, creator_id, output = sys.argv[2:]
kind, row = next((kind, row) for kind, row in catalog_lineage.records(root) if row["id"] == record_id)
value = catalog_lineage.default_lineage(root, kind, row)
value.update(origin_instance_id=instance_id, creator_id=creator_id)
Path(output).write_bytes(catalog_lineage.canonical(value))
'''
    lineage_output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([python, "-c", script, str(root), record_id,
                    profile["instance_id"], profile["creator_id"], str(lineage_output)],
                   cwd=project_code, capture_output=True, text=True,
                   check=True, timeout=120)
    profile_output.write_text(
        "contract_version: " + json.dumps("instance-profile/v1") + "\n"
        "instance_id: " + json.dumps(profile["instance_id"]) + "\n"
        "creator_id: " + json.dumps(profile["creator_id"]) + "\n"
        "mode: " + json.dumps(str(profile.get("mode", "new-clone"))) + "\n"
        "permissions:\n  local_knowledge_write: " + str(permissions.get("local_knowledge_write") is True).lower() + "\n",
        encoding="utf-8")


def sync_catalog(project_code: Path, python: str, root: Path) -> None:
    """Regenerate the target catalog with the Project's native generator."""
    script = r'''
import sys
from pathlib import Path
from tools import catalog_sync

root = Path(sys.argv[1]).resolve()
for path, content in catalog_sync.expected_files(root).items():
    path.write_text(content, encoding="utf-8")
'''
    subprocess.run([python, "-c", script, str(root)], cwd=project_code,
                   capture_output=True, text=True, check=True, timeout=120)


def verify(root: Path, project_code: Path, python: str, expected_path: Path,
           output: Path, run_id: str, projection_path: Path) -> dict:
    root = root.resolve()
    project_code = project_code.resolve()
    expected = read(expected_path)
    projection = read(projection_path)
    if not isinstance(projection, dict) or projection.get("status") != "APPLIED" or projection.get("projection_id") != run_id:
        raise ValueError("PUBLIC_PROJECTION_NOT_APPLIED")
    ids = projection.get("public_ids")
    if not isinstance(ids, list) or not ids or {item.get("record_id") for item in expected} != set(ids):
        raise ValueError("PUBLIC_PROJECTION_RECORDS_MISMATCH")
    process = subprocess.run([python, "-c", _child_check_script(), str(root), str(expected_path)],
                             cwd=project_code, capture_output=True, text=True, timeout=120)
    try:
        receipt = json.loads(process.stdout)
    except ValueError as exc:
        raise ValueError("PROJECT_NATIVE_RECEIVER_RESPONSE_INVALID") from exc
    if process.returncode or receipt.get("status") != "VERIFIED":
        raise ValueError("PROJECT_NATIVE_RECEIVER_BLOCKED")
    receipt.update({"contract_version": "local-plan-delivery-receipt/v1", "run_id": run_id,
                    "target": "project-local", "target_root_role": "public_projection_root"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical(receipt) + b"\n")
    return receipt


def finalize(state_path: Path, receipt_path: Path) -> dict:
    state = read(state_path)
    receipt = read(receipt_path)
    if not isinstance(state, dict) or not isinstance(receipt, dict) or receipt.get("status") != "VERIFIED":
        raise ValueError("PROJECT_LOCAL_RECEIPT_REQUIRED")
    contract = state.get("delivery_contract")
    if not isinstance(contract, dict) or contract.get("contract_version") != "delivery-contract/v1" or contract.get("target") != "project-local":
        raise ValueError("PROJECT_LOCAL_CONTRACT_REQUIRED")
    state["local_delivery_receipt"] = receipt
    state.update(projection_status="PROJECTED", run_status="COMPLETED", stop_reason=None, next_action=None)
    state["delivery_completion"] = completion(state, contract)
    state["completion_status"] = state["delivery_completion"]["status"]
    if state["completion_status"] != "COMPLETED":
        raise ValueError("DELIVERY_COMPLETION_INCOMPLETE")
    temporary = state_path.with_name(state_path.name + ".pending")
    if state_path.is_symlink() or temporary.is_symlink():
        raise ValueError("STATE_SYMLINK")
    temporary.write_bytes(canonical(state))
    os.replace(temporary, state_path)
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--root", required=True, type=Path)
    check.add_argument("--project-code", required=True, type=Path)
    check.add_argument("--python", default=sys.executable)
    check.add_argument("--expected", required=True, type=Path)
    check.add_argument("--projection-result", required=True, type=Path)
    check.add_argument("--output", required=True, type=Path)
    check.add_argument("--run-id", required=True)
    finish = sub.add_parser("finalize")
    finish.add_argument("--state", required=True, type=Path)
    finish.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "verify":
        result = verify(args.root, args.project_code, args.python, args.expected, args.output, args.run_id, args.projection_result)
    else:
        result = finalize(args.state, args.receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
