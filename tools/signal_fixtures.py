"""Instantiate a fictional Self Model contract envelope only for offline tests.

The tracked template is not an owner export. No actual export envelope, even
one claiming to be synthetic, is exempt from the tracked-file privacy gate.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def synthetic_self_export() -> dict:
    template = json.loads((ROOT / "tests/fixtures/signal/self_export_bundle.json").read_text(encoding="utf-8"))
    if template["fixture_version"] != "synthetic-self-signal-template/v1" or template["subject"] != "subject/fixture":
        raise ValueError("expected a fictional subject/fixture signal template")
    return {"contract_version": "research-signal-export/v1", **template["envelope_fields"]}
