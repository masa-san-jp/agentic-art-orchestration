#!/usr/bin/env python3
"""Boundary adapters for child-repository data.

The adapter accepts an already-approved derived self-model record. It never
reads or transports raw voice content; the child repository remains its
authority and only an opaque locator crosses this boundary.
"""

from __future__ import annotations

import copy

from tools.validate import validate_signal


class AdapterError(ValueError):
    """A child record cannot be safely represented by the boundary contract."""


_FORBIDDEN_RAW_FIELDS = {
    "raw_voice",
    "raw_voice_text",
    "raw_voice_body",
    "raw_audio",
    "voice_body",
    "private_raw",
    "restricted",
}
_FORBIDDEN_GRAPH_FIELDS = {
    "graph",
    "nodes",
    "edges",
    "canonical_graph",
    "graph_data",
    "entity_payload",
}
_REQUIRED_FIELDS = {
    "signal_id",
    "commit",
    "entity_id",
    "source_locator",
    "evidence_locator",
    "evidence_kind",
    "statement",
    "certainty",
    "unknowns",
    "constraints",
    "validity",
    "freshness",
    "generated_at",
    "adapter_version",
    "consent_scope",
    "export_permitted",
    "seeks",
    "protects",
    "avoids",
    "tensions",
    "recurring_patterns",
    "raw_voice_locator",
    "traits",
    "states",
    "contexts",
}


def _fail(detail: str, remediation: str) -> AdapterError:
    return AdapterError(f"self-model adapter: {detail}; remediation: {remediation}")


def adapt_self_model_signal(record: dict) -> dict:
    """Convert one approved derived record to normalized-research-signal/v1.

    The input is deliberately an explicit boundary DTO rather than a child
    repository schema. Required values are copied, not inferred or flattened.
    Unknown optional child fields are ignored, while known raw-data fields are
    rejected so a future child schema cannot accidentally widen the export.
    """
    if not isinstance(record, dict):
        raise _fail("input must be an object", "pass one approved derived record")

    leaked = sorted(_FORBIDDEN_RAW_FIELDS.intersection(record))
    if leaked:
        raise _fail(
            f"forbidden raw field(s) present: {leaked!r}",
            "export raw_voice_locator only and keep raw voice in self-model",
        )

    missing = sorted(field for field in _REQUIRED_FIELDS if field not in record)
    if missing:
        raise _fail(
            f"required input field(s) missing: {missing!r}",
            "provide approved provenance, evidence, consent, and freshness fields",
        )

    if record.get("repository", "self-model") != "self-model":
        raise _fail(
            f"source repository must be 'self-model', got {record.get('repository')!r}",
            "use the repository ID declared in config/repositories.yaml",
        )
    if record["export_permitted"] is not True:
        raise _fail(
            "export_permitted must be true",
            "obtain an approved consent scope before exporting derived content",
        )
    if not isinstance(record["consent_scope"], str) or not record["consent_scope"].strip():
        raise _fail(
            "consent_scope must be non-empty",
            "include the child repository's explicit consent scope",
        )

    signal = {
        "contract_version": "normalized-research-signal/v1",
        "signal_id": record["signal_id"],
        "signal_kind": "self",
        "source": {
            "repository": "self-model",
            "commit": record["commit"],
            "entity_ids": [record["entity_id"]],
            "locators": [record["source_locator"]],
        },
        "statement": record["statement"],
        "evidence_refs": [
            {
                "locator": record["evidence_locator"],
                "kind": record["evidence_kind"],
                "entity_id": record["entity_id"],
            }
        ],
        "certainty": copy.deepcopy(record["certainty"]),
        "unknowns": copy.deepcopy(record["unknowns"]),
        "constraints": copy.deepcopy(record["constraints"]),
        "validity": copy.deepcopy(record["validity"]),
        "freshness": copy.deepcopy(record["freshness"]),
        "adapter": {
            "name": "self-model-export",
            "version": record["adapter_version"],
        },
        "generated_at": record["generated_at"],
        "domain": {
            "self_model": {
                "consent_scope": record["consent_scope"],
                "export_permitted": True,
                "seeks": copy.deepcopy(record["seeks"]),
                "protects": copy.deepcopy(record["protects"]),
                "avoids": copy.deepcopy(record["avoids"]),
                "tensions": copy.deepcopy(record["tensions"]),
                "recurring_patterns": copy.deepcopy(record["recurring_patterns"]),
                "raw_voice_locator": record["raw_voice_locator"],
                "traits": copy.deepcopy(record["traits"]),
                "states": copy.deepcopy(record["states"]),
                "contexts": copy.deepcopy(record["contexts"]),
            }
        },
    }
    errors = validate_signal(signal, "self-model adapter output")
    if errors:
        raise AdapterError("\n".join(errors))
    return signal


def adapt_art_history_signal(record: dict) -> dict:
    """Convert one art-history record without copying its canonical graph."""
    if not isinstance(record, dict):
        raise _fail("input must be an object", "pass one art-history entity record")

    leaked = sorted(_FORBIDDEN_GRAPH_FIELDS.intersection(record))
    if leaked:
        raise AdapterError(
            "art-history adapter: canonical graph payload field(s) present: "
            f"{leaked!r}; remediation: export stable IDs and canonical graph locators only"
        )

    required = {
        "signal_id",
        "commit",
        "entity_id",
        "source_locator",
        "evidence_locator",
        "evidence_kind",
        "statement",
        "certainty",
        "unknowns",
        "constraints",
        "validity",
        "freshness",
        "generated_at",
        "adapter_version",
        "entity_kind",
        "time",
        "geo",
        "relations",
        "canonical_graph_locator",
    }
    missing = sorted(field for field in required if field not in record)
    if missing:
        raise _fail(
            f"art-history required input field(s) missing: {missing!r}",
            "provide stable entity, relation, evidence, and graph locator fields",
        )
    if not isinstance(record["relations"], list) or not record["relations"]:
        raise _fail(
            "relations must be a non-empty list",
            "include each exported relation with its stable target ID, evidence, and certainty",
        )

    for index, relation in enumerate(record["relations"]):
        if not isinstance(relation, dict):
            raise _fail(
                f"relations[{index}] must be an object",
                "use stable relation fields rather than a copied graph node",
            )
        relation_missing = sorted(
            field for field in ("target_entity_id", "relation", "certainty", "evidence_refs")
            if field not in relation
        )
        if relation_missing:
            raise _fail(
                f"relations[{index}] missing field(s): {relation_missing!r}",
                "retain relation evidence and interpretive certainty",
            )
        if relation["target_entity_id"] == record["entity_id"]:
            raise _fail(
                f"relations[{index}] target_entity_id repeats the source entity",
                "reference the related stable entity ID without copying the canonical graph",
            )
        if not isinstance(relation["evidence_refs"], list) or not relation["evidence_refs"]:
            raise _fail(
                f"relations[{index}].evidence_refs must be non-empty",
                "retain the evidence locator for every relation",
            )
        if any(not isinstance(locator, str) or not locator for locator in relation["evidence_refs"]):
            raise _fail(
                f"relations[{index}].evidence_refs contains an invalid locator",
                "use opaque evidence locators rather than inline source content",
            )

    signal = {
        "contract_version": "normalized-research-signal/v1",
        "signal_id": record["signal_id"],
        "signal_kind": "art-history",
        "source": {
            "repository": "art-history",
            "commit": record["commit"],
            "entity_ids": [record["entity_id"]],
            "locators": [record["source_locator"]],
        },
        "statement": record["statement"],
        "evidence_refs": [
            {
                "locator": record["evidence_locator"],
                "kind": record["evidence_kind"],
                "entity_id": record["entity_id"],
            }
        ],
        "certainty": copy.deepcopy(record["certainty"]),
        "unknowns": copy.deepcopy(record["unknowns"]),
        "constraints": copy.deepcopy(record["constraints"]),
        "validity": copy.deepcopy(record["validity"]),
        "freshness": copy.deepcopy(record["freshness"]),
        "adapter": {
            "name": "art-history-export",
            "version": record["adapter_version"],
        },
        "generated_at": record["generated_at"],
        "domain": {
            "art_history": {
                "entity_kind": record["entity_kind"],
                "time": record["time"],
                "geo": record["geo"],
                "relations": copy.deepcopy(record["relations"]),
                "canonical_graph_locator": record["canonical_graph_locator"],
            }
        },
    }
    errors = validate_signal(signal, "art-history adapter output")
    if errors:
        raise AdapterError("\n".join(errors))
    return signal


def adapt_marketing_signal(record: dict) -> dict:
    """Convert one marketing trend record with explicit freshness metadata."""
    if not isinstance(record, dict):
        raise _fail("input must be an object", "pass one marketing trend record")

    required = {
        "signal_id",
        "commit",
        "entity_id",
        "source_locator",
        "evidence_locator",
        "evidence_kind",
        "statement",
        "certainty",
        "unknowns",
        "constraints",
        "validity",
        "freshness",
        "generated_at",
        "adapter_version",
        "stage",
        "revalidate_at",
        "expires_at",
        "retrieved",
        "vendor_interest",
        "counterevidence",
        "prediction_status",
    }
    missing = sorted(field for field in required if field not in record)
    if missing:
        raise _fail(
            f"marketing required input field(s) missing: {missing!r}",
            "provide stage, freshness, retrieval, interest, counterevidence, and expiry fields",
        )
    freshness = record["freshness"]
    if not isinstance(freshness, dict):
        raise _fail(
            "freshness must be an object",
            "provide status, retrieved_at, and revalidate_at explicitly",
        )
    if freshness.get("revalidate_at") != record["revalidate_at"]:
        raise _fail(
            "domain revalidate_at must match common freshness.revalidate_at",
            "preserve one machine-checkable revalidation date",
        )
    if not isinstance(record["counterevidence"], list):
        raise _fail(
            "counterevidence must be a list",
            "retain counterevidence as an explicit machine-checkable collection",
        )
    if not isinstance(record["retrieved"], dict):
        raise _fail(
            "retrieved must be an object",
            "keep retrieval time and method separate from certainty",
        )
    if record.get("repository", "marketing-trends") != "marketing-trends":
        raise _fail(
            f"source repository must be 'marketing-trends', got {record.get('repository')!r}",
            "use the repository ID declared in config/repositories.yaml",
        )

    signal = {
        "contract_version": "normalized-research-signal/v1",
        "signal_id": record["signal_id"],
        "signal_kind": "marketing",
        "source": {
            "repository": "marketing-trends",
            "commit": record["commit"],
            "entity_ids": [record["entity_id"]],
            "locators": [record["source_locator"]],
        },
        "statement": record["statement"],
        "evidence_refs": [
            {
                "locator": record["evidence_locator"],
                "kind": record["evidence_kind"],
                "entity_id": record["entity_id"],
            }
        ],
        "certainty": copy.deepcopy(record["certainty"]),
        "unknowns": copy.deepcopy(record["unknowns"]),
        "constraints": copy.deepcopy(record["constraints"]),
        "validity": copy.deepcopy(record["validity"]),
        "freshness": copy.deepcopy(record["freshness"]),
        "adapter": {
            "name": "marketing-trends-export",
            "version": record["adapter_version"],
        },
        "generated_at": record["generated_at"],
        "domain": {
            "marketing": {
                "stage": record["stage"],
                "freshness": record["freshness"]["status"],
                "revalidate_at": record["revalidate_at"],
                "expires_at": record["expires_at"],
                "retrieved": copy.deepcopy(record["retrieved"]),
                "vendor_interest": record["vendor_interest"],
                "counterevidence": copy.deepcopy(record["counterevidence"]),
                "prediction_status": record["prediction_status"],
            }
        },
    }
    errors = validate_signal(signal, "marketing adapter output")
    if errors:
        raise AdapterError("\n".join(errors))
    return signal


def adapt_viewer_response_signal(record: dict) -> dict:
    """Pass the viewer child-domain DTO to its dedicated boundary unchanged.

    Viewer responses use ``viewer-response-record/v1`` rather than the three
    normalized research signal kinds. The dedicated viewer gate owns validation;
    this function exists so manifest adapters are explicit without pretending the
    record is a marketing or personal signal.
    """
    if not isinstance(record, dict):
        raise _fail("viewer response input must be an object", "pass one viewer-response-record/v1 record")
    return copy.deepcopy(record)
