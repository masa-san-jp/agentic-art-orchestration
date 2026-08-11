#!/usr/bin/env python3
"""Import normalized research signals without coupling to child schemas."""

from __future__ import annotations

import copy
import re

from tools.validate import validate_signal


class ConsumerCompatibilityError(ValueError):
    """A signal cannot be safely imported by the declared consumer contract."""


CONSUMER_CONTRACT = "normalized-research-signal/v1"
_CONTRACT_RE = re.compile(r"^normalized-research-signal/v([0-9]+)$")


def _major(contract_version: object) -> int | None:
    if not isinstance(contract_version, str):
        return None
    match = _CONTRACT_RE.fullmatch(contract_version)
    return int(match.group(1)) if match else None


def _error(detail: str, remediation: str) -> ConsumerCompatibilityError:
    return ConsumerCompatibilityError(
        f"consumer contract: {detail}; remediation: {remediation}"
    )


def _project_signal(signal: dict) -> dict:
    """Retain the consumer contract projection and ignore minor extensions."""
    return {
        "contract_version": signal["contract_version"],
        "signal_id": signal["signal_id"],
        "signal_kind": signal["signal_kind"],
        "source": copy.deepcopy(signal["source"]),
        "statement": signal["statement"],
        "certainty": copy.deepcopy(signal["certainty"]),
        "unknowns": copy.deepcopy(signal["unknowns"]),
        "constraints": copy.deepcopy(signal["constraints"]),
        "validity": copy.deepcopy(signal["validity"]),
        "freshness": copy.deepcopy(signal["freshness"]),
        "adapter": copy.deepcopy(signal["adapter"]),
        "domain": copy.deepcopy(signal["domain"]),
    }


def import_signals(
    signals: list[dict],
    expected_contract: str = CONSUMER_CONTRACT,
) -> dict:
    """Validate and import signals into a provenance-preserving research package."""
    expected_major = _major(expected_contract)
    if expected_major is None:
        raise _error(
            f"unsupported expected contract {expected_contract!r}",
            "configure normalized-research-signal/v1",
        )
    if not isinstance(signals, list) or not signals:
        raise _error("signals must be a non-empty list", "provide at least one valid signal")

    imported: list[dict] = []
    provenance: list[dict] = []
    seen_ids: set[str] = set()
    for index, signal in enumerate(signals):
        if not isinstance(signal, dict):
            raise _error(
                f"signals[{index}] must be an object",
                "pass normalized signal objects from an adapter",
            )
        actual_major = _major(signal.get("contract_version"))
        if actual_major != expected_major:
            raise _error(
                f"signals[{index}] major version {actual_major!r} is incompatible with {expected_major}",
                "adapt the signal to the consumer's major contract or reject it",
            )
        errors = validate_signal(signal, f"consumer input signals[{index}]")
        if errors:
            raise ConsumerCompatibilityError("\n".join(errors))
        signal_id = signal["signal_id"]
        if signal_id in seen_ids:
            raise _error(
                f"duplicate signal_id {signal_id!r}",
                "retain one source signal ID per imported package",
            )
        seen_ids.add(signal_id)
        projection = _project_signal(signal)
        imported.append(projection)
        provenance.append(
            {
                "signal_id": signal_id,
                "source_repository": signal["source"]["repository"],
                "source_commit": signal["source"]["commit"],
            }
        )

    return {
        "contract_version": expected_contract,
        "signals": imported,
        "provenance": provenance,
    }
