#!/usr/bin/env python3
"""Create-only Google Drive artifact adapter with a networkless fake."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Mapping

from tools.validate import validate_external_artifact


class DriveArtifactError(ValueError):
    """A Drive artifact operation is invalid or would violate append-only policy."""


IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def _error(detail: str, remediation: str) -> DriveArtifactError:
    return DriveArtifactError(f"drive adapter: {detail}; remediation: {remediation}")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _bytes(content: str | bytes) -> bytes:
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not isinstance(content, bytes):
        raise _error("content must be UTF-8 text or bytes", "send the output payload to Drive and keep it out of the Git envelope")
    return content


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class FakeDrive:
    """A networkless Drive-like store that keeps content outside the artifact envelope."""

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}
        self._metadata: dict[str, dict] = {}
        self.operations: list[dict] = []

    def create_file(self, *, mime_type: str, content: bytes) -> str:
        file_id = f"drive-file-{len(self._files) + 1:03d}"
        self._files[file_id] = bytes(content)
        self._metadata[file_id] = {"mime_type": mime_type}
        self.operations.append({"operation": "CREATE", "provider_file_id": file_id})
        return file_id

    def read_content(self, provider_file_id: str) -> bytes:
        try:
            return bytes(self._files[provider_file_id])
        except KeyError as exc:
            raise _error("provider file does not exist in fake Drive", "use the opaque ID returned by a successful CREATE") from exc

    def file_count(self) -> int:
        return len(self._files)

    def update_file(self, provider_file_id: str, content: bytes) -> None:
        del provider_file_id, content
        raise _error("UPDATE is forbidden", "create a new artifact and link it with lineage")

    def delete_file(self, provider_file_id: str) -> None:
        del provider_file_id
        raise _error("DELETE is forbidden", "retain the immutable artifact and change access through a human gate")


class DriveArtifactAdapter:
    """Persist content to a Drive service and return only a validated envelope."""

    def __init__(self, drive: FakeDrive) -> None:
        self.drive = drive
        self._idempotency: dict[str, dict] = {}
        self._artifact_ids: dict[str, dict] = {}
        self._registry: list[dict] = []

    @staticmethod
    def _validate_idempotency_key(value: object) -> str:
        if not isinstance(value, str) or IDEMPOTENCY_KEY.fullmatch(value) is None:
            raise _error("idempotency_key is invalid", "use a stable non-empty key without whitespace")
        return value

    @staticmethod
    def _prepare_metadata(metadata: Mapping[str, object], content_hash: str) -> dict:
        if not isinstance(metadata, Mapping):
            raise _error("artifact metadata must be an object", "pass only the external-artifact metadata envelope")
        prepared = copy.deepcopy(dict(metadata))
        if prepared.get("contract_version") not in (None, "external-artifact/v1"):
            raise _error("unsupported artifact contract", "use external-artifact/v1")
        if prepared.get("operation") not in (None, "CREATE"):
            raise _error("UPDATE and DELETE operations are forbidden", "create a new artifact and preserve lineage")
        if prepared.get("provider") not in (None, "google-drive"):
            raise _error("provider must be google-drive", "use the approved Google Drive adapter")
        if "provider_file_id" in prepared:
            raise _error("provider_file_id must not be supplied by the caller", "let the CREATE response provide a new opaque file ID")
        if "content_hash" in prepared:
            raise _error("content_hash must be computed from the payload", "do not trust a caller-supplied hash")
        prepared["contract_version"] = "external-artifact/v1"
        prepared["operation"] = "CREATE"
        prepared["provider"] = "google-drive"
        prepared["provider_file_id"] = "pending-file-id"
        prepared["content_hash"] = content_hash
        errors = validate_external_artifact(prepared, "drive adapter preflight")
        if errors:
            raise DriveArtifactError("\n".join(errors))
        return prepared

    @staticmethod
    def _fingerprint(metadata: Mapping[str, object], content_hash: str) -> str:
        return _canonical({"metadata": dict(metadata), "content_hash": content_hash})

    def create_artifact(
        self,
        *,
        content: str | bytes,
        metadata: Mapping[str, object],
        idempotency_key: str,
    ) -> dict:
        """Create once and replay the same metadata for an identical request."""
        payload = _bytes(content)
        if not payload:
            raise _error("empty artifact content is not allowed", "create a non-empty user output or keep it transient")
        key = self._validate_idempotency_key(idempotency_key)
        content_hash = _sha256(payload)
        prepared = self._prepare_metadata(metadata, content_hash)
        artifact_id = prepared["artifact_id"]
        fingerprint = self._fingerprint(prepared, content_hash)

        previous = self._idempotency.get(key)
        if previous is not None:
            if previous["fingerprint"] != fingerprint:
                raise _error(
                    f"idempotency key {key!r} was reused with different metadata or content",
                    "resume the original CREATE or use a new interaction-scoped key",
                )
            return {
                "operation": "REPLAY",
                "created": False,
                "idempotency_key": key,
                "artifact": copy.deepcopy(previous["artifact"]),
            }

        if artifact_id in self._artifact_ids:
            raise _error(
                f"artifact_id {artifact_id!r} already exists",
                "use a new immutable artifact ID rather than overwriting an existing output",
            )

        provider_file_id = self.drive.create_file(
            mime_type=prepared["mime_type"],
            content=payload,
        )
        artifact = copy.deepcopy(prepared)
        artifact["provider_file_id"] = provider_file_id
        errors = validate_external_artifact(artifact, "drive adapter output")
        if errors:
            raise DriveArtifactError("\n".join(errors))

        self._idempotency[key] = {"fingerprint": fingerprint, "artifact": copy.deepcopy(artifact)}
        self._artifact_ids[artifact_id] = copy.deepcopy(artifact)
        self._registry.append(copy.deepcopy(artifact))
        return {
            "operation": "CREATE",
            "created": True,
            "idempotency_key": key,
            "artifact": copy.deepcopy(artifact),
        }

    def create(self, *, content: str | bytes, metadata: Mapping[str, object], idempotency_key: str) -> dict:
        """Short alias for the create-only adapter surface."""
        return self.create_artifact(content=content, metadata=metadata, idempotency_key=idempotency_key)

    def update_artifact(self, provider_file_id: str, content: str | bytes) -> None:
        del provider_file_id, content
        raise _error("UPDATE is forbidden", "create a new artifact and link it with lineage")

    def update(self, provider_file_id: str, content: str | bytes) -> None:
        self.update_artifact(provider_file_id, content)

    def delete_artifact(self, provider_file_id: str) -> None:
        del provider_file_id
        raise _error("DELETE is forbidden", "retain the immutable artifact and use a human access gate")

    def delete(self, provider_file_id: str) -> None:
        self.delete_artifact(provider_file_id)

    def registry_snapshot(self) -> list[dict]:
        """Return metadata-only append-only registry contents."""
        return copy.deepcopy(self._registry)
