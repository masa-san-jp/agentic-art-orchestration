#!/usr/bin/env python3
"""Owner-scoped, resumable knowledge exchange for AAK artifact records."""
from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {"NO_CHANGE", "COMMITTED", "INDEX_PENDING", "REJECTED", "CONFLICT", "ALREADY_APPLIED"}


class KnowledgeCycleError(ValueError):
    pass


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def registry(path: Path = ROOT / "config/knowledge-owners.yaml") -> dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data.get("contract_version") != "knowledge-owner-registry/v1":
        raise KnowledgeCycleError("unknown owner registry")
    owners = data.get("owners")
    result = {item["id"]: item for item in owners or []}
    if len(result) != 8 or len(result) != len(owners or []):
        raise KnowledgeCycleError("registry must contain eight unique owners")
    return result


def _safe_ref(value: object) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def validate_record(record: Mapping, owner: str, allowed_collection: str) -> None:
    required = {
        "contract_version", "record_id", "revision", "origin_instance_id", "creator_id",
        "owner_repository", "collection_id", "kind", "payload_schema", "payload_ref",
        "content_sha256", "sources", "derived_from", "epistemic_status", "lifecycle",
        "applicability", "rights", "access_scope", "consent_ref", "created_at",
        "reviewed_at", "valid_until", "producer", "supersedes", "invalidates",
    }
    if set(record) != required or record.get("contract_version") != "artifact-record/v1":
        raise KnowledgeCycleError("record is not the closed artifact-record/v1 contract")
    if record.get("owner_repository") != owner:
        raise KnowledgeCycleError("owner mismatch")
    if record.get("collection_id") != allowed_collection:
        raise KnowledgeCycleError("collection is not authorized")
    if not _safe_ref(record.get("payload_ref")):
        raise KnowledgeCycleError("unsafe payload_ref")
    if record.get("lifecycle") == "candidate":
        raise KnowledgeCycleError("unverified candidate cannot be committed")
    if record.get("epistemic_status") not in {"observed", "externally-supported", "inferred", "proposed", "simulated", "unknown"}:
        raise KnowledgeCycleError("unknown epistemic status")
    digest = record.get("content_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise KnowledgeCycleError("invalid content hash")


def prepare(records: list[Mapping], owner: str, collection: str, operation_id: str, run_id: str) -> dict:
    if owner not in registry():
        raise KnowledgeCycleError("unknown owner")
    return {"operation_id": operation_id, "run_id": run_id, "owner": owner,
            "collection": collection, "records": [dict(r) for r in records]}


class LocalOwner:
    """Synthetic/real-local owner adapter. It never writes a remote or another owner."""
    def __init__(self, root: Path, owner: str, collection: str, code_commit: str, knowledge_commit: str):
        self.root, self.owner, self.collection = root, owner, collection
        self.code_commit, self.knowledge_commit = code_commit, knowledge_commit
        self.records = root / "records"
        self.receipts = root / "receipts"
        self.index_path = root / "index.json"

    def commit(self, bundle: Mapping, expected_parent: str) -> dict:
        if bundle["owner"] != self.owner or bundle["collection"] != self.collection:
            return self._receipt(bundle, "REJECTED", expected_parent, None, "owner or collection mismatch")
        operation = self.receipts / f"{bundle['operation_id']}.json"
        if operation.exists():
            previous = json.loads(operation.read_text(encoding="utf-8"))
            if previous["target_parent"] == expected_parent:
                return {**previous, "status": "ALREADY_APPLIED", "reason": "operation already applied"}
            return self._receipt(bundle, "CONFLICT", expected_parent, None, "operation replay differs")
        if expected_parent != self.knowledge_commit:
            return self._receipt(bundle, "CONFLICT", expected_parent, None, "knowledge parent CAS mismatch")
        accepted = []
        for record in bundle["records"]:
            try:
                validate_record(record, self.owner, self.collection)
            except KnowledgeCycleError as exc:
                return self._receipt(bundle, "REJECTED", expected_parent, None, str(exc), rejected=[record.get("record_id", "unknown")])
            key = f"{record['origin_instance_id']}--{self.owner}--{record['record_id']}--r{record['revision']}.json"
            target = self.records / key
            payload = canonical(record)
            if target.exists():
                if target.read_bytes() != payload:
                    return self._receipt(bundle, "CONFLICT", expected_parent, None, "REVISION_CONFLICT")
                continue
            accepted.append((target, payload, record["record_id"]))
        if not accepted:
            return self._receipt(bundle, "NO_CHANGE", expected_parent, expected_parent, "all records already present")
        tree_hash = sha256(expected_parent.encode() + b"".join(payload for _, payload, _ in accepted))
        for target, payload, _ in accepted:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        self.knowledge_commit = tree_hash
        receipt = self._receipt(bundle, "COMMITTED", expected_parent, tree_hash, "owner-local commit created", accepted=[x[2] for x in accepted])
        operation.parent.mkdir(parents=True, exist_ok=True)
        operation.write_bytes(canonical(receipt))
        return receipt

    def index(self, receipt: Mapping, fail: bool = False) -> dict:
        if receipt["status"] not in {"COMMITTED", "ALREADY_APPLIED", "INDEX_PENDING"}:
            return dict(receipt)
        if fail:
            return {**receipt, "status": "INDEX_PENDING", "reason": "owner index failed; commit retained"}
        entries = []
        for path in sorted(self.records.glob("*.json")):
            item = json.loads(path.read_text(encoding="utf-8"))
            entries.append({"owner": self.owner, "record_id": item["record_id"], "revision": item["revision"],
                            "lifecycle": item["lifecycle"], "access_scope": item["access_scope"],
                            "content_sha256": item["content_sha256"], "ref": path.relative_to(self.root).as_posix(),
                            "invalidates": item["invalidates"]})
        body = {"contract_version": "knowledge-index/v1", "code_commit": self.code_commit,
                "knowledge_commit": self.knowledge_commit, "entries": entries}
        self.index_path.write_bytes(canonical(body))
        return {**receipt, "index_commit": self.knowledge_commit, "index_hash": sha256(self.index_path.read_bytes()), "reason": "commit and index verified"}

    def retrieve(self, query: str, creator: str, access_scope: str) -> dict:
        if not self.index_path.exists():
            return _trace(query, self, [], "UNAVAILABLE")
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        invalidated = {x.get("record_id") for e in data["entries"] for x in e.get("invalidates", []) if isinstance(x, dict)}
        active = [e for e in data["entries"] if e["lifecycle"] == "accepted" and e["access_scope"] == access_scope and e["record_id"] not in invalidated]
        records = [{"record_id": e["record_id"], "revision": e["revision"], "owner": self.owner,
                    "decision": "adopted", "reason": "active owner record selected for current query",
                    "affected": [query]} for e in active]
        return _trace(query, self, records, "REUSED" if records else "EMPTY_HISTORY")

    def _receipt(self, bundle, status, parent, target, reason, accepted=None, rejected=None):
        return {"contract_version":"knowledge-write-receipt/v1", "operation_id":bundle["operation_id"],
                "run_id":bundle["run_id"], "owner":self.owner, "collection":self.collection,
                "target_parent":parent, "target_commit":target, "accepted_ids":accepted or [],
                "rejected_ids":rejected or [], "schema_version":"artifact-record/v1",
                "policy_version":"knowledge-cycle/v1", "index_commit":None, "index_hash":None,
                "status":status, "reason":reason}


def _trace(query: str, owner: LocalOwner, records: list[dict], status: str) -> dict:
    return {"contract_version":"reuse-trace/v1", "query":query,
            "selection_policy_version":"knowledge-retrieval/v1",
            "input_snapshot":{"code_commit":owner.code_commit,"knowledge_commit":owner.knowledge_commit},
            "seen_scope":[owner.collection], "records":records, "status":status}


def dispatch(bundles: list[Mapping], providers: Mapping[str, LocalOwner], fail_owner: str | None = None) -> dict:
    receipts = []
    for bundle in bundles:
        provider = providers[bundle["owner"]]
        receipt = provider.commit(bundle, provider.knowledge_commit)
        receipts.append(provider.index(receipt, fail=provider.owner == fail_owner))
    failed = [r["owner"] for r in receipts if r["status"] in {"REJECTED", "CONFLICT", "INDEX_PENDING"}]
    return {"contract_version":"knowledge-dispatch-report/v1", "status":"PARTIAL" if failed else "COMMITTED",
            "receipts":receipts, "pending_owners":failed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("registry", "validate"))
    parser.add_argument("--record", type=Path)
    parser.add_argument("--owner")
    parser.add_argument("--collection")
    args = parser.parse_args()
    try:
        if args.command == "registry":
            print(json.dumps({"owners": registry()}, ensure_ascii=False, sort_keys=True))
            return 0
        if not args.record or not args.owner or not args.collection:
            raise KnowledgeCycleError("validate requires --record, --owner, and --collection")
        validate_record(json.loads(args.record.read_text(encoding="utf-8")), args.owner, args.collection)
        print(json.dumps({"status": "PASSED", "record": str(args.record)}, sort_keys=True))
        return 0
    except (KnowledgeCycleError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAILED", "detail": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
