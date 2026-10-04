#!/usr/bin/env python3
"""Create and validate Git-external portable Self Model exports without changing the owner contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT = "portable-self-export/v1"
RECEIPT_CONTRACT = "portable-self-export-receipt/v1"
EMPTY_REMEDIATION = (
    "入口のヒアリングに答える／self-model-notes の初回手順（init と同意）へ。"
    "同意済みの self signal が育ってから、同じ run を再開する。"
)


class SelfExportError(ValueError):
    def __init__(self, code: str, remediation: str):
        self.code = code
        self.remediation = remediation
        super().__init__(f"{code}: {remediation}")


def content_hash(payload: object) -> str:
    try:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise SelfExportError("SELF_EXPORT_INVALID", "use JSON without non-finite values or invalid text") from None
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise SelfExportError("SELF_EXPORT_INVALID", "use JSON with unique object keys")
        result[key] = value
    return result


def _invalid_constant(value: str):
    raise SelfExportError("SELF_EXPORT_INVALID", "use JSON without non-finite numeric values")


def timestamp(value: object) -> datetime:
    try:
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value,
        ):
            raise ValueError()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise SelfExportError("SELF_EXPORT_INVALID", "use RFC3339 timestamps with an explicit timezone") from None


def external_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    # Reject any Git checkout, including a foreign checkout and ignored paths.
    probe = resolved.parent
    while not probe.exists():
        probe = probe.parent
    result = subprocess.run(["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
    if resolved == ROOT or ROOT in resolved.parents or result.returncode == 0:
        raise SelfExportError("SELF_EXPORT_REPOSITORY_OVERLAP", "use a location outside repositories accessible only to the owner")
    return resolved


def validate_payload(payload: object, purpose: str) -> None:
    from tools.validate import validate_signal_export, validate_signal
    from tools.adapters import adapt_self_model_signal, AdapterError
    from tools.security import check_export, scan_payload
    if validate_signal_export(payload, "self-export"):
        raise SelfExportError("SELF_EXPORT_INVALID", "repair the owner research-signal-export/v1 envelope")
    if payload["source_repository"] != "self-model" or payload["purpose"] != purpose:
        raise SelfExportError("SELF_EXPORT_SCOPE_MISMATCH", "use a self-model export for the requested purpose")
    timestamp(payload["generated_at"])
    if scan_payload(payload):
        raise SelfExportError("SELF_EXPORT_INVALID", "remove forbidden data at the owner boundary")
    for record in payload["signals"]:
        if record.get("repository") != "self-model" or record.get("commit") != payload["source_commit"]:
            raise SelfExportError("SELF_EXPORT_INVALID", "keep each record's repository and source commit consistent")
        try:
            signal = adapt_self_model_signal(record)
        except (AdapterError, KeyError, TypeError, ValueError):
            raise SelfExportError("SELF_EXPORT_INVALID", "repair the owner signal record") from None
        if validate_signal(signal, "self-export") or check_export(signal, "self-export"):
            raise SelfExportError("SELF_EXPORT_INVALID", "use only validated, consent-approved derived signals")


def validate_portable(envelope: object, purpose: str, *, now: datetime | None = None) -> tuple[dict, dict]:
    fields = {"contract_version", "export_id", "generated_at", "expires_at", "source_commit", "content_sha256", "payload"}
    if not isinstance(envelope, dict) or set(envelope) != fields or envelope.get("contract_version") != CONTRACT:
        raise SelfExportError("SELF_EXPORT_INVALID", "create a portable-self-export/v1 envelope with tools/self_export.py")
    if not isinstance(envelope["export_id"], str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", envelope["export_id"]) is None:
        raise SelfExportError("SELF_EXPORT_INVALID", "retain the original opaque export ID")
    validate_payload(envelope["payload"], purpose)
    payload = envelope["payload"]
    if envelope["source_commit"] != payload["source_commit"] or envelope["generated_at"] != payload["generated_at"]:
        raise SelfExportError("SELF_EXPORT_INVALID", "retain the owner generation timestamp and 40-character source commit")
    if envelope["content_sha256"] != content_hash(payload):
        raise SelfExportError("SELF_EXPORT_HASH_MISMATCH", "transfer the original export unchanged or export again at the owner machine")
    generated = timestamp(envelope["generated_at"])
    expiry = timestamp(envelope["expires_at"])
    current = now or datetime.now(timezone.utc)
    if generated > current or expiry <= generated:
        raise SelfExportError("SELF_EXPORT_INVALID", "choose an expiry after generation and do not use a future-dated export")
    if expiry <= current:
        raise SelfExportError("SELF_EXPORT_EXPIRED", "export again on the machine holding the owner profile and consent")
    receipt = {key: envelope[key] for key in fields - {"payload", "contract_version"}}
    receipt["contract_version"] = RECEIPT_CONTRACT
    return payload, receipt


def read_export(path: Path, purpose: str) -> tuple[dict, dict]:
    try:
        envelope = json.loads(external_path(path).read_text(encoding="utf-8"),
                              object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SelfExportError("SELF_EXPORT_INVALID", "provide a readable Git-external portable export JSON") from None
    return validate_portable(envelope, purpose)


def create_export(workspace_root: Path, profile_root: Path, output: Path, purpose: str,
                  expires_at: str, python: str) -> dict:
    from tools.ingest_signals import _export
    from tools.validate import load_yaml
    from tools.run import _guard_pinned_workspace
    destination = external_path(output)
    if destination.exists():
        raise SelfExportError("SELF_EXPORT_EXISTS", "choose a new filename; exports are create-only")
    _guard_pinned_workspace(workspace_root)
    repository = next(item for item in load_yaml(ROOT / "config/repositories.yaml")["repositories"] if item["id"] == "self-model")
    payload = _export(repository, workspace_root, purpose, python, profile_root)
    envelope = {"contract_version": CONTRACT, "export_id": "self-export:" + uuid.uuid4().hex,
                "generated_at": payload.get("generated_at"), "expires_at": expires_at,
                "source_commit": payload.get("source_commit"), "content_sha256": content_hash(payload), "payload": payload}
    _, receipt = validate_portable(envelope, purpose)
    if not payload["signals"]:
        raise SelfExportError("SELF_MODEL_EMPTY", EMPTY_REMEDIATION)
    # Exclusive creation, owner read/write only; never overwrite an earlier export.
    import os
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return {"status": "PASSED", "self_export": receipt}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--profile-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expires-at", required=True, help="owner-selected RFC3339 expiration")
    parser.add_argument("--purpose", default="artistic-research")
    parser.add_argument("--child-python", default=sys.executable)
    args = parser.parse_args(argv)
    try:
        report = create_export(args.workspace_root, args.profile_root, args.output, args.purpose, args.expires_at, args.child_python)
    except (SelfExportError, RuntimeError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, SelfExportError) else "SELF_EXPORT_UNAVAILABLE"
        remediation = exc.remediation if isinstance(exc, SelfExportError) else "repair the pinned workspace and authorized owner profile"
        print(json.dumps({"status": "BLOCKED", "stop_reason": code, "remediation": remediation}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
