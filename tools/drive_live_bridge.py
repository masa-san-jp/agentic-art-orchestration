#!/usr/bin/env python3
"""Provider-neutral, append-only Google Drive CREATE/read-back bridge."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from tools.drive_adapter import DriveArtifactAdapter, DriveArtifactError
from tools.security import scan_payload
from tools.validate import _schema_errors, load_json, load_yaml, validate_drive_live_contract, validate_external_artifact


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/drive-live-policy.yaml"
SCHEMA_PATH = ROOT / "schemas/drive-live-evidence.schema.json"
EPOCH = "1970-01-01T00:00:00Z"
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
FOLDER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,}$")


class DriveLiveError(ValueError):
    """A Drive live operation is invalid or crosses the append-only boundary."""


class DriveLiveProvider(Protocol):
    """Only the provider-neutral READ/CREATE port is exposed."""

    def search_by_idempotency(self, approved_folder_id: str, marker: str) -> list[Mapping[str, object]]: ...

    def create_file(self, approved_folder_id: str, name: str, mime_type: str, content: bytes, properties: Mapping[str, str] | None = None) -> Mapping[str, object]: ...

    def read_file(self, provider_file_id: str) -> Mapping[str, object]: ...


def _error(detail: str, remediation: str) -> DriveLiveError:
    return DriveLiveError(f"drive live bridge: {detail}; remediation: {remediation}")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    payload = value if isinstance(value, bytes) else _canonical(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _bytes(value: str | bytes) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bytes):
        return bytes(value)
    raise _error("content must be UTF-8 text or bytes", "keep artifact content outside the Git evidence envelope")


class GoogleDriveProvider:
    """Minimal Google Drive v3 provider exposing only list, create, and read."""

    def __init__(self, token: str, api_root: str = "https://www.googleapis.com") -> None:
        if not isinstance(token, str) or not token:
            raise _error("live mode requires a Google Drive token", "set the configured credential environment variable without committing it")
        self.token = token
        self.api_root = api_root.rstrip("/")

    def _request(self, method: str, path: str, body: bytes | None = None, content_type: str | None = None) -> dict:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "agentic-art-orchestration-drive-live",
        }
        if body is not None:
            headers["Content-Type"] = content_type or "application/json"
        request = Request(self.api_root + path, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=20) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            detail = getattr(exc, "code", None) or type(exc).__name__
            raise _error(f"Google Drive {method} request failed ({detail})", "inspect access without retrying a mutation blindly") from exc
        if not isinstance(value, dict):
            raise _error("Google Drive returned an unexpected response", "inspect the provider response before retrying")
        return value

    @staticmethod
    def _reference(value: Mapping[str, object]) -> dict:
        provider_file_id = value.get("id") or value.get("provider_file_id")
        if not isinstance(provider_file_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{3,}", provider_file_id) is None:
            raise _error("Google Drive returned an invalid opaque file ID", "do not expose or retry an unsafe provider response")
        parents = value.get("parents", [])
        return {
            "provider_file_id": provider_file_id,
            "parent_folder_id": parents[0] if isinstance(parents, list) and parents and isinstance(parents[0], str) else value.get("parent_folder_id"),
            "mime_type": value.get("mimeType") or value.get("mime_type"),
            "content_hash": value.get("content_hash"),
            "metadata_verified": value.get("metadata_verified", False),
            "properties": dict(value.get("appProperties", {})) if isinstance(value.get("appProperties"), Mapping) else dict(value.get("properties", {})) if isinstance(value.get("properties"), Mapping) else {},
        }

    def search_by_idempotency(self, approved_folder_id: str, marker: str) -> list[Mapping[str, object]]:
        query = f"'{approved_folder_id}' in parents and trashed = false and appProperties has {{ key='orchestration_idempotency_marker' and value='{marker}' }}"
        path = "/drive/v3/files?" + urlencode({
            "q": query,
            "spaces": "drive",
            "pageSize": "10",
            "fields": "files(id,name,mimeType,parents,size,appProperties)",
        })
        value = self._request("GET", path)
        files = value.get("files", [])
        if not isinstance(files, list):
            raise _error("Google Drive search response is invalid", "inspect the provider response before any CREATE")
        return [self._reference(item) for item in files if isinstance(item, Mapping)]

    def create_file(self, approved_folder_id: str, name: str, mime_type: str, content: bytes, properties: Mapping[str, str] | None = None) -> Mapping[str, object]:
        boundary = "drive-orchestration-boundary"
        metadata = {"name": name, "parents": [approved_folder_id], "mimeType": mime_type, "appProperties": dict(properties or {})}
        prefix = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            + json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
            + f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
        body = prefix + bytes(content) + f"\r\n--{boundary}--\r\n".encode("ascii")
        path = "/upload/drive/v3/files?" + urlencode({"uploadType": "multipart", "fields": "id,name,mimeType,parents,size,appProperties"})
        return self._reference(self._request("POST", path, body, f"multipart/related; boundary={boundary}"))

    def read_file(self, provider_file_id: str) -> Mapping[str, object]:
        path = f"/drive/v3/files/{quote(provider_file_id, safe='')}?" + urlencode({"fields": "id,name,mimeType,parents,size,appProperties"})
        metadata = self._reference(self._request("GET", path))
        if metadata["mime_type"] == "application/vnd.google-apps.document":
            metadata["metadata_verified"] = True
            return metadata
        media_path = f"/drive/v3/files/{quote(provider_file_id, safe='')}?alt=media"
        request = Request(self.api_root + media_path, method="GET", headers={"Authorization": f"Bearer {self.token}", "User-Agent": "agentic-art-orchestration-drive-live"})
        try:
            with urlopen(request, timeout=20) as response:
                metadata["content_hash"] = _hash(response.read())
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            detail = getattr(exc, "code", None) or type(exc).__name__
            raise _error(f"Google Drive content read-back failed ({detail})", "retain the existing artifact and investigate without replacement") from exc
        return metadata


class FakeDriveLiveProvider:
    """Networkless provider that models a folder-scoped CREATE and read-back."""

    def __init__(self) -> None:
        self._files: dict[str, dict] = {}
        self.operations: list[dict] = []

    def search_by_idempotency(self, approved_folder_id: str, marker: str) -> list[Mapping[str, object]]:
        self.operations.append({"operation": "READ", "folder": approved_folder_id})
        return [
            {"provider_file_id": file_id, "parent_folder_id": item["parent_folder_id"], "properties": dict(item.get("properties", {}))}
            for file_id, item in sorted(self._files.items())
            if item["parent_folder_id"] == approved_folder_id and item["name"] == marker
        ]

    def create_file(self, approved_folder_id: str, name: str, mime_type: str, content: bytes, properties: Mapping[str, str] | None = None) -> Mapping[str, object]:
        provider_file_id = f"drive-live-file-{len(self._files) + 1:03d}"
        self._files[provider_file_id] = {
            "parent_folder_id": approved_folder_id,
            "name": name,
            "mime_type": mime_type,
            "content": bytes(content),
            "properties": dict(properties or {}),
        }
        self.operations.append({"operation": "CREATE", "folder": approved_folder_id, "provider_file_id": provider_file_id})
        return {"provider_file_id": provider_file_id}

    def read_file(self, provider_file_id: str) -> Mapping[str, object]:
        try:
            item = self._files[provider_file_id]
        except KeyError as exc:
            raise _error("provider file is missing during read-back", "retain the create response and do not create a replacement blindly") from exc
        self.operations.append({"operation": "READ", "provider_file_id": provider_file_id})
        return {
            "provider_file_id": provider_file_id,
            "parent_folder_id": item["parent_folder_id"],
            "mime_type": item["mime_type"],
            "content_hash": _hash(item["content"]),
            "properties": dict(item.get("properties", {})),
        }

    @property
    def file_count(self) -> int:
        return len(self._files)


class DriveLiveBridge:
    """Create a new immutable Drive artifact and verify it by reading back metadata/hash."""

    def __init__(self, provider: DriveLiveProvider | None = None, policy: Mapping[str, object] | None = None) -> None:
        self.provider = provider
        self.policy = dict(policy or load_yaml(POLICY_PATH))
        errors = validate_drive_live_contract(self.policy, load_json(SCHEMA_PATH))
        if errors:
            raise _error("policy is invalid: " + "; ".join(errors), "repair the Drive create-only contract before use")
        self._idempotency: dict[str, dict] = {}

    def _folder_id(self, folder_id: str | None, mode: str) -> str:
        if folder_id is None:
            if mode == "plan":
                folder_id = self.policy["approved_folder"]["fixture_id"]
            else:
                env_name = self.policy["approved_folder"]["id_env_var"]
                folder_id = os.environ.get(env_name, "")
        if not isinstance(folder_id, str) or FOLDER_PATTERN.fullmatch(folder_id) is None:
            raise _error("approved folder ID is missing or invalid", "pass an explicitly approved Drive folder ID; never use root implicitly")
        return folder_id

    @staticmethod
    def _marker(idempotency_key: str) -> str:
        return f"agentic-art-orchestration:{_hash(idempotency_key)[:32]}"

    @staticmethod
    def _artifact_reference(artifact: Mapping[str, object]) -> dict:
        return {
            "artifact_id": artifact["artifact_id"],
            "provider_file_id": artifact["provider_file_id"],
            "content_hash": artifact["content_hash"],
            "lineage": copy.deepcopy(artifact["lineage"]),
        }

    def _result(self, *, run_id: str, mode: str, status: str, operation: str, folder_id: str, key: str, content_hash: str, artifact: Mapping[str, object] | None, remote_operations: list[dict]) -> dict:
        result = {
            "contract_version": "drive-live/v1",
            "run_id": run_id,
            "mode": mode.upper(),
            "status": status,
            "operation": operation,
            "provider": "google-drive",
            "approved_folder_id_hash": _hash(folder_id),
            "idempotency_key_hash": _hash(key),
            "content_hash": content_hash,
            "artifact": self._artifact_reference(artifact) if artifact is not None else None,
            "remote_operations": remote_operations,
        }
        errors = _schema_errors(result, load_json(SCHEMA_PATH))
        if errors:
            raise _error("evidence violates its schema: " + "; ".join(errors), "repair the bridge result before any live operation")
        return result

    def create(self, *, content: str | bytes, metadata: Mapping[str, object], idempotency_key: str, mode: str = "plan", folder_id: str | None = None, run_id: str = "DRIVE-LIVE-001:attempt-1", confirm_live: bool = False) -> dict:
        if mode not in {"plan", "live"} or not ID_PATTERN.fullmatch(run_id) or not isinstance(idempotency_key, str) or not ID_PATTERN.fullmatch(idempotency_key):
            raise _error("mode, run_id, or idempotency_key is invalid", "use stable identifiers and plan/live mode")
        if mode == "live" and confirm_live is not True:
            raise _error("live mode requires explicit confirmation", "pass confirm_live=True only after an approved sandbox folder is verified")
        if scan_payload(dict(metadata)):
            raise _error("artifact metadata crosses the security boundary", "remove raw content, credentials, and direct identifiers")
        approved_folder_id = self._folder_id(folder_id, mode)
        payload = _bytes(content)
        if not payload:
            raise _error("empty artifact content is not allowed", "create a non-empty artifact or keep output transient")
        content_hash = _hash(payload)
        prepared = DriveArtifactAdapter._prepare_metadata(metadata, content_hash)
        fingerprint = _canonical({"metadata": prepared, "content_hash": content_hash})
        previous = self._idempotency.get(idempotency_key)
        if previous is not None:
            if previous["fingerprint"] != fingerprint:
                raise _error("idempotency key was reused with different content or metadata", "use a new immutable artifact ID and key")
            replay = copy.deepcopy(previous["result"])
            replay["status"] = "REPLAYED"
            replay["operation"] = "REPLAY"
            return replay
        if mode == "plan":
            return self._result(run_id=run_id, mode=mode, status="PLANNED", operation="NONE", folder_id=approved_folder_id, key=idempotency_key, content_hash=content_hash, artifact=None, remote_operations=[])
        if self.provider is None:
            raise _error("live mode has no provider", "inject an authenticated provider with only READ/CREATE methods")
        marker = self._marker(idempotency_key)
        folder_hash = _hash(approved_folder_id)
        key_hash = _hash(idempotency_key)
        remote_operations = [{"operation": "READ", "approved_folder_id_hash": folder_hash, "idempotency_key_hash": key_hash}]
        matches = list(self.provider.search_by_idempotency(approved_folder_id, marker))
        if len(matches) > 1:
            raise _error("multiple provider files match the idempotency marker", "stop and resolve the ambiguity manually; do not delete or overwrite")
        if matches:
            provider_file_id = matches[0].get("provider_file_id")
            if not isinstance(provider_file_id, str):
                raise _error("existing provider reference is invalid", "retain the opaque provider response for manual review")
            status, operation = "REPLAYED", "REPLAY"
        else:
            expected_properties = {
                "orchestration_idempotency_marker": marker,
                "request_fingerprint": _hash(fingerprint),
            }
            created = self.provider.create_file(approved_folder_id, marker, prepared["mime_type"], payload, expected_properties)
            provider_file_id = created.get("provider_file_id")
            if not isinstance(provider_file_id, str):
                raise _error("provider CREATE returned no opaque file ID", "do not retry until the response is understood")
            status, operation = "CREATED", "CREATE"
            remote_operations.append({"operation": "CREATE", "approved_folder_id_hash": folder_hash, "idempotency_key_hash": key_hash})
        readback = self.provider.read_file(provider_file_id)
        expected_properties = {
            "orchestration_idempotency_marker": marker,
            "request_fingerprint": _hash(fingerprint),
        }
        if readback.get("parent_folder_id") != approved_folder_id or readback.get("properties") != expected_properties or (readback.get("content_hash") != content_hash and readback.get("metadata_verified") is not True):
            raise _error("Drive read-back verification failed", "retain the existing artifact and investigate without replacement")
        remote_operations.append({"operation": "READ", "approved_folder_id_hash": folder_hash, "idempotency_key_hash": key_hash, "provider_file_id_hash": _hash(provider_file_id)})
        artifact = copy.deepcopy(prepared)
        artifact["provider_file_id"] = provider_file_id
        artifact_errors = validate_external_artifact(artifact, "drive live bridge output")
        if artifact_errors:
            raise _error("artifact envelope failed read-back validation: " + "; ".join(artifact_errors), "retain the external file and repair the envelope contract")
        result = self._result(run_id=run_id, mode=mode, status=status, operation=operation, folder_id=approved_folder_id, key=idempotency_key, content_hash=content_hash, artifact=artifact, remote_operations=remote_operations)
        self._idempotency[idempotency_key] = {"fingerprint": fingerprint, "result": copy.deepcopy(result)}
        return result
