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
PUBLIC_PROJECTION_FINDING_CODES = {
    "UNKNOWN_CLEARANCE",
    "MISSING_APPROVAL",
    "APPROVAL_MISMATCH",
    "APPROVAL_EXPIRED",
    "TARGET_CONFLICT",
    "TARGET_DIRTY",
    "LAYOUT_INVALID",
    "SOURCE_PATH_UNSAFE",
    "SOURCE_HASH_MISMATCH",
    "FORBIDDEN_CONTENT",
    "CREDENTIAL",
    "PRIVATE_URL",
    "ABSOLUTE_PATH",
    "FORBIDDEN_ARTIFACT",
    "UNAPPROVED_MEDIA",
    "INTERNAL_REFERENCE",
    "REMOTE_OPERATION",
    "ROLLBACK_FAILED",
}
_PUBLIC_FORBIDDEN_KEY_NAMES = {key.casefold() for key in FORBIDDEN_KEYS}
_PUBLIC_DIRECT_IDENTIFIER_KEYS = {
    "direct_identifier",
    "email",
    "phone",
    "user_id",
    "person_id",
    "internal_id",
    "drive_id",
    "issue_id",
    "signed_url",
    "private_url",
}
_PUBLIC_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:Users|home|private|tmp|var|Volumes|System|opt)/")
_PUBLIC_INTERNAL_URL = re.compile(
    r"(?i)(?:https?://(?:drive|docs)\.google\.com/|"
    r"https?://github\.com/[^/\s]+/[^/\s]+/(?:issues|pull|commit)/|"
    r"git@github\.com:[^\s]+\.git)"
)
_PUBLIC_FORBIDDEN_ARTIFACT = re.compile(r"(?i)\.(?:gdoc|gsheet|gslides)(?:$|[?#\s])")
_PUBLIC_FORBIDDEN_LITERAL = re.compile(r"(?i)\b(?:PRIVATE_RAW|RESTRICTED)\b")


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


def scan_public_projection(payload: object, source: str = "public-projection") -> list[dict]:
    """Scan a projection envelope without copying forbidden values into findings.

    The request contract intentionally retains internal source provenance. This
    scanner therefore reports only values that are never safe at the public
    boundary (credentials, raw/restricted classes, direct identifiers, private
    provider locators, absolute paths, and provider-native document artifacts).
    Policy decisions such as unknown clearance are reported by the projection
    contract validator, not inferred from arbitrary prose here.
    """
    findings: list[dict] = []
    for key, child, location in _walk(payload):
        key_name = key.casefold()
        if key_name in _PUBLIC_FORBIDDEN_KEY_NAMES:
            findings.append(_finding("FORBIDDEN_CONTENT", source, location, "remove PRIVATE_RAW, RESTRICTED, or raw content before projection"))
        if key_name in _PUBLIC_DIRECT_IDENTIFIER_KEYS:
            findings.append(_finding("INTERNAL_REFERENCE", source, location, "replace direct identifiers with an approved opaque reference"))
        if isinstance(child, str):
            if SECRET_PATTERN.search(child) or TOKEN_PATTERN.search(child):
                findings.append(_finding("CREDENTIAL", source, location, "remove credential-like values and rotate exposed credentials"))
            if _PUBLIC_FORBIDDEN_LITERAL.search(child):
                findings.append(_finding("FORBIDDEN_CONTENT", source, location, "remove restricted or raw content before projection"))
            if _PUBLIC_FORBIDDEN_ARTIFACT.search(child):
                findings.append(_finding("FORBIDDEN_ARTIFACT", source, location, "export approved plain files instead of provider-native artifacts"))
            if _PUBLIC_ABSOLUTE_PATH.search(child):
                findings.append(_finding("ABSOLUTE_PATH", source, location, "use a relative public locator or an opaque hash"))
            if _PUBLIC_INTERNAL_URL.search(child):
                findings.append(_finding("PRIVATE_URL", source, location, "remove internal provider URLs and use an opaque public reference"))
            if key_name.endswith("locator") and (child.startswith("/") or ".." in child.split("/")):
                findings.append(_finding("SOURCE_PATH_UNSAFE", source, location, "use a normalized relative locator without traversal"))
    if isinstance(payload, str):
        if SECRET_PATTERN.search(payload) or TOKEN_PATTERN.search(payload):
            findings.append(_finding("CREDENTIAL", source, "$", "remove credential-like values and rotate exposed credentials"))
        if _PUBLIC_FORBIDDEN_LITERAL.search(payload):
            findings.append(_finding("FORBIDDEN_CONTENT", source, "$", "remove restricted or raw content before projection"))
        if _PUBLIC_FORBIDDEN_ARTIFACT.search(payload):
            findings.append(_finding("FORBIDDEN_ARTIFACT", source, "$", "export approved plain files instead of provider-native artifacts"))
        if _PUBLIC_ABSOLUTE_PATH.search(payload):
            findings.append(_finding("ABSOLUTE_PATH", source, "$", "use a relative public locator or an opaque hash"))
        if _PUBLIC_INTERNAL_URL.search(payload):
            findings.append(_finding("PRIVATE_URL", source, "$", "remove internal provider URLs and use an opaque public reference"))
    return _dedupe_findings(findings)


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
