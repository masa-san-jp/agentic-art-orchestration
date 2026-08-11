#!/usr/bin/env python3
"""Enforce the parent data, secret, and consent boundary before export."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]

try:
    from tools.validate import validate_signal
except ModuleNotFoundError:  # pragma: no cover - exercised by direct CLI use
    sys.path.insert(0, str(ROOT))
    from tools.validate import validate_signal


class SecurityBoundaryError(ValueError):
    """A payload crosses a forbidden or unapproved boundary."""


FORBIDDEN_KEYS = {
    "PRIVATE_RAW",
    "RESTRICTED",
    "credential",
    "direct_identifier",
    "raw_voice_body",
    "raw_voice_text",
    "raw_audio",
    "personal_evidence",
    "email_body",
    "calendar_details",
}
SECRET_PATTERN = re.compile(
    r"(?is)\b(?:password|secret|token|api[_-]?key|private[_-]?key|credential)\b\s*[:=]\s*\S+"
)
TOKEN_PATTERN = re.compile(r"\b(?:ghp|github_pat|sk)-[A-Za-z0-9_-]{8,}\b")
ALLOWED_SELF_CONSENT = {"approved-derived-only"}


def _error(detail: str, remediation: str) -> SecurityBoundaryError:
    return SecurityBoundaryError(f"security boundary: {detail}; remediation: {remediation}")


def _finding(code: str, source: str, location: str, remediation: str) -> dict:
    return {"code": code, "source": source, "location": location, "remediation": remediation}


def _walk(value: object, location: str = "$"):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key), child, f"{location}.{key}"
            yield from _walk(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{location}[{index}]")


def scan_payload(payload: object, source: str = "payload") -> list[dict]:
    """Return sanitized findings; never copy sensitive values into evidence."""
    findings: list[dict] = []
    for key, child, location in _walk(payload):
        if key in FORBIDDEN_KEYS:
            findings.append(_finding("forbidden-data", source, location, "remove the forbidden data class before export"))
        if isinstance(child, str) and (SECRET_PATTERN.search(child) or TOKEN_PATTERN.search(child)):
            findings.append(_finding("secret", source, location, "remove the credential-like value and rotate it if exposed"))
    if isinstance(payload, str) and (SECRET_PATTERN.search(payload) or TOKEN_PATTERN.search(payload)):
        findings.append(_finding("secret", source, "$", "remove the credential-like value and rotate it if exposed"))
    return _dedupe_findings(findings)


def _dedupe_findings(findings: list[dict]) -> list[dict]:
    unique = {json.dumps(finding, ensure_ascii=False, sort_keys=True): finding for finding in findings}
    return [unique[key] for key in sorted(unique)]


def check_export(signal: Mapping[str, object], source: str = "signal") -> list[dict]:
    """Validate a normalized signal and require explicit self-model consent."""
    findings = scan_payload(signal, source)
    validation_errors = validate_signal(signal, source)
    if validation_errors:
        findings.append(_finding("invalid-signal", source, "$", "repair the normalized signal at the owning adapter boundary"))
    domain = signal.get("domain") if isinstance(signal, Mapping) else None
    self_model = domain.get("self_model") if isinstance(domain, Mapping) else None
    if isinstance(self_model, Mapping):
        if self_model.get("export_permitted") is not True:
            findings.append(_finding("unapproved-export", source, "$.domain.self_model.export_permitted", "obtain explicit approved-derived consent before export"))
        if self_model.get("consent_scope") not in ALLOWED_SELF_CONSENT:
            findings.append(_finding("unapproved-export", source, "$.domain.self_model.consent_scope", "limit export to approved-derived-only scope"))
    return _dedupe_findings(findings)


def audit_boundary(payloads: Mapping[str, object], signals: Mapping[str, Mapping[str, object]] | None = None) -> dict:
    """Scan named parent payloads and signals without mutating them."""
    findings: list[dict] = []
    for source in sorted(payloads):
        findings.extend(scan_payload(payloads[source], source))
    for source in sorted(signals or {}):
        findings.extend(check_export(signals[source], source))
    findings = _dedupe_findings(findings)
    return {
        "version": 1,
        "status": "PASSED" if not findings else "FAILED",
        "blocking": bool(findings),
        "findings": findings,
        "checked_payloads": sorted(payloads),
        "checked_signals": sorted(signals or {}),
    }


def _load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check parent payloads and signal exports against the security boundary")
    parser.add_argument("--payload", action="append", type=Path, default=[])
    parser.add_argument("--signal", action="append", type=Path, default=[])
    parser.add_argument("--offline-fixture", action="store_true", help="scan generated parent outputs and valid signal fixtures")
    parser.add_argument("--output", type=Path, default=ROOT / "data/security.json")
    args = parser.parse_args()
    payloads: dict[str, object] = {}
    signals: dict[str, Mapping[str, object]] = {}
    try:
        paths = list(args.payload)
        signal_paths = list(args.signal)
        if args.offline_fixture:
            paths.extend(sorted((ROOT / "data").glob("*.json")))
            signal_paths.extend(sorted((ROOT / "tests/fixtures/signal").glob("valid_*.json")))
        for path in paths:
            resolved = path if path.is_absolute() else Path.cwd() / path
            payloads[str(resolved.relative_to(ROOT)) if resolved.is_relative_to(ROOT) else str(resolved)] = _load_json(resolved)
        for path in signal_paths:
            resolved = path if path.is_absolute() else Path.cwd() / path
            signals[str(resolved.relative_to(ROOT)) if resolved.is_relative_to(ROOT) else str(resolved)] = _load_json(resolved)
        result = audit_boundary(payloads, signals)
        _write_atomic(args.output.resolve(), json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result["blocking"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
