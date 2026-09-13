#!/usr/bin/env python3
"""Owner-scoped, resumable knowledge exchange for AAK artifact records."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import re
import subprocess
import tempfile
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.path_safety import external_path as _safe_external_path

import yaml

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
    from tools.validate import _schema_errors, load_json
    errors = _schema_errors(record, load_json(ROOT / "schemas/artifact-record.schema.json"))
    if errors:
        raise KnowledgeCycleError("invalid artifact schema")
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
    if "\\" in record["payload_ref"] or any(ord(c) < 32 for c in record["payload_ref"]):
        raise KnowledgeCycleError("unsafe payload_ref")
    for field in ("created_at", "reviewed_at", "valid_until"):
        value = record[field]
        if value is not None:
            try:
                timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("timezone absent")
            except (ValueError, TypeError, AttributeError) as exc:
                raise KnowledgeCycleError("invalid timestamp") from exc
    if record.get("lifecycle") == "candidate":
        raise KnowledgeCycleError("unverified candidate cannot be committed")
    for field in ("sources", "derived_from", "supersedes", "invalidates"):
        for ref in record[field]:
            if "record_id" in ref and (not isinstance(ref["record_id"], str) or
                                       not ref["record_id"] or
                                       type(ref.get("revision")) is not int or ref["revision"] < 1):
                raise KnowledgeCycleError("invalid record reference")
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


def reference_key(record, fallback=None):
    fallback = fallback or {}
    return (record.get("origin_instance_id", fallback.get("origin_instance_id")),
            record.get("owner_repository", fallback.get("owner_repository")),
            record["record_id"], record["revision"])


def revalidation_candidates(entries):
    """Keep invalidated history, and enumerate its dependent revisions."""
    invalid = set()
    for entry in entries:
        invalid.update(reference_key(ref, entry) for ref in entry["invalidates"] + entry["supersedes"])
        if entry["lifecycle"] in {"revoked", "superseded"}:
            invalid.add(reference_key(entry))
    dependents = set()
    changed = True
    while changed:
        changed = False
        for entry in entries:
            key = reference_key(entry)
            if key in invalid or key in dependents:
                continue
            if any(reference_key(ref, entry) in invalid | dependents
                   for ref in entry["derived_from"] + entry["sources"] if "record_id" in ref):
                dependents.add(key)
                changed = True
    return [{"origin_instance_id": k[0], "owner_repository": k[1],
             "record_id": k[2], "revision": k[3]} for k in sorted(dependents)]


def assert_acyclic_sources(entries):
    graph = {reference_key(e): [reference_key(r, e) for r in e["sources"] + e["derived_from"]
                               if "record_id" in r] for e in entries}
    visiting, visited = set(), set()
    def visit(key):
        if key in visiting:
            raise KnowledgeCycleError("cyclic source ancestry")
        if key in visited or key not in graph:
            return
        visiting.add(key)
        for parent in graph[key]:
            visit(parent)
        visiting.remove(key)
        visited.add(key)
    for key in graph:
        visit(key)


class LocalOwner:
    """Dedicated bare Git store; immutable commits, atomic ref CAS, no remote effects."""

    def __init__(self, root: Path, owner: str, collection: str, code_commit: str,
                 knowledge_commit: str | None = None, *, creator: str,
                 payload_validator: Callable[[Mapping, bytes], bool],
                 initializer: Callable[[Path], None] | None = None):
        if owner not in registry() or not callable(payload_validator):
            raise KnowledgeCycleError("owner and payload validator must be explicit")
        for value in (owner, collection, creator):
            if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value) is None:
                raise KnowledgeCycleError("unsafe owner identity")
        if re.fullmatch(r"[0-9a-f]{40}", code_commit) is None:
            raise KnowledgeCycleError("invalid code commit")
        try:
            root = _safe_external_path(root)
        except ValueError as exc:
            raise KnowledgeCycleError("symlink store forbidden") from exc
        self.root, self.owner, self.collection = root, owner, collection
        self.creator, self.code_commit = creator, code_commit
        self.payload_validator = payload_validator
        self.index_path = self.root / "index.json"
        self.git_dir = self.root / "objects.git"
        self.ref = "refs/heads/knowledge"
        identity = {"owner": owner, "collection": collection, "creator": creator}
        if not self.root.exists():
            self.root.mkdir(parents=True)
        marker = self.root / "store.json"
        if not marker.exists():
            if any(self.root.iterdir()):
                raise KnowledgeCycleError("refuse adoption of populated unregistered store")
            if initializer is None:
                subprocess.run(["git", "init", "--bare", "--quiet", str(self.git_dir)], check=True,
                               capture_output=True)
                tree = self._git(["mktree"], b"").strip().decode()
                commit = self._git(["commit-tree", tree], canonical(identity)).strip().decode()
                self._git(["update-ref", self.ref, commit, "0" * 40])
            else:
                # Native owner initialization happens off to the side. A failed
                # initializer leaves the final store empty and retryable.
                with tempfile.TemporaryDirectory(prefix="owner-init-", dir=self.root.parent) as temporary:
                    staging = Path(temporary) / "objects.git"
                    initializer(staging)
                    if staging.is_symlink() or subprocess.check_output(
                        ["git", "--git-dir", str(staging), "rev-parse", "--is-bare-repository"], text=True).strip() != "true":
                        raise KnowledgeCycleError("native initializer did not create a bare owner store")
                    subprocess.run(["git", "--git-dir", str(staging), "rev-parse", "--verify", self.ref + "^{commit}"],
                                   check=True, capture_output=True)
                    staging.rename(self.git_dir)
            self._atomic(marker, canonical(identity))
        elif marker.is_symlink() or json.loads(marker.read_bytes()) != identity:
            raise KnowledgeCycleError("store identity mismatch")
        if self.git_dir.is_symlink():
            raise KnowledgeCycleError("symlink Git store forbidden")
        self.knowledge_commit = knowledge_commit or self._head()
        if re.fullmatch(r"[0-9a-f]{40}", self.knowledge_commit) is None:
            raise KnowledgeCycleError("invalid knowledge commit")
        self._git(["merge-base", "--is-ancestor", self.knowledge_commit, self._head()])

    def _git(self, args, body=None, index=None):
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("GIT_"):
                env.pop(key)
        env.update(GIT_AUTHOR_NAME="knowledge-owner", GIT_AUTHOR_EMAIL="local@example.invalid",
                   GIT_COMMITTER_NAME="knowledge-owner", GIT_COMMITTER_EMAIL="local@example.invalid",
                   GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        result = subprocess.run(["git", "--git-dir", str(self.git_dir), *args],
                                input=body, capture_output=True, env=env)
        if result.returncode:
            raise KnowledgeCycleError("local Git operation failed: " + args[0])
        return result.stdout

    def _head(self):
        return self._git(["rev-parse", self.ref]).strip().decode()

    @staticmethod
    def _atomic(path, body):
        if path.is_symlink():
            raise KnowledgeCycleError("symlink output forbidden")
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".knowledge-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _files(self, commit):
        return self._git(["ls-tree", "-r", "--name-only", commit]).decode().splitlines()

    def _read(self, commit, path):
        return self._git(["show", commit + ":" + path])

    @staticmethod
    def _key(record):
        return sha256(canonical([record["origin_instance_id"], record["owner_repository"],
                                 record["record_id"], record["revision"]]))

    def commit(self, bundle: Mapping, expected_parent: str, *, payloads=None) -> dict:
        receipt = lambda status, target, reason: self._receipt(bundle, status, expected_parent, target, reason)
        if bundle.get("owner") != self.owner or bundle.get("collection") != self.collection:
            return receipt("REJECTED", None, "owner or collection mismatch")
        operation_path = "operations/" + sha256(canonical(bundle["operation_id"])) + ".json"
        head = self._head()
        files = self._files(head)
        digest = sha256(canonical(bundle))
        if operation_path in files:
            operation = json.loads(self._read(head, operation_path))
            if operation["bundle_hash"] != digest or operation["parent"] != expected_parent:
                return receipt("CONFLICT", None, "operation replay differs")
            target = self._git(["log", "-1", "--format=%H", head, "--", operation_path]).strip().decode()
            self.knowledge_commit = head
            return self._receipt(bundle, "ALREADY_APPLIED", expected_parent, target,
                                 "verified operation replay", accepted=operation["accepted_ids"])
        if expected_parent != head:
            return receipt("CONFLICT", None, "knowledge parent CAS mismatch")
        updates, accepted = {}, []
        for record in bundle["records"]:
            try:
                validate_record(record, self.owner, self.collection)
                if record["creator_id"] != self.creator:
                    raise KnowledgeCycleError("active creator mismatch")
                if not record["payload_ref"].startswith("payloads/"):
                    raise KnowledgeCycleError("payload outside owner allowlist")
                payload = (payloads or {}).get(record["payload_ref"])
                if not isinstance(payload, bytes) or sha256(payload) != record["content_sha256"]:
                    raise KnowledgeCycleError("missing or hash-mismatched payload")
                if self.payload_validator(record, payload) is not True:
                    raise KnowledgeCycleError("owner payload validation failed")
            except Exception:
                return receipt("REJECTED", None, "record or owner payload validation failed")
            key = self._key(record)
            path = "records/" + key + ".json"
            body = canonical(record)
            if path in files:
                if self._read(head, path) != body:
                    return receipt("CONFLICT", None, "REVISION_CONFLICT")
                continue
            if path in updates and updates[path] != body:
                return receipt("CONFLICT", None, "REVISION_CONFLICT in bundle")
            updates[path] = body
            if record["payload_ref"] in updates and updates[record["payload_ref"]] != payload:
                return receipt("CONFLICT", None, "payload locator conflict in bundle")
            updates[record["payload_ref"]] = payload
            accepted.append(record["record_id"])
        if not updates:
            return receipt("NO_CHANGE", head, "all records already present")
        history = [json.loads(self._read(head, path)) for path in files if path.startswith("records/")]
        try:
            assert_acyclic_sources(history + list(bundle["records"]))
        except KnowledgeCycleError:
            return receipt("REJECTED", None, "cyclic source ancestry")
        updates[operation_path] = canonical({"bundle_hash": digest, "parent": expected_parent,
                                            "accepted_ids": accepted})
        with tempfile.TemporaryDirectory(prefix="knowledge-index-") as temporary:
            index = Path(temporary) / "index"
            self._git(["read-tree", head], index=index)
            for path, body in sorted(updates.items()):
                blob = self._git(["hash-object", "-w", "--stdin"], body).strip().decode()
                self._git(["update-index", "--add", "--cacheinfo", "100644", blob, path], index=index)
            tree = self._git(["write-tree"], index=index).strip().decode()
            target = self._git(["commit-tree", tree, "-p", head],
                               canonical({"operation": bundle["operation_id"]})).strip().decode()
        try:
            self._git(["update-ref", self.ref, target, head])
        except KnowledgeCycleError:
            return receipt("CONFLICT", None, "knowledge parent CAS lost")
        self.knowledge_commit = target
        return self._receipt(bundle, "COMMITTED", head, target, "Git commit and tree verified",
                             accepted=accepted)

    def index(self, receipt: Mapping, fail: bool = False) -> dict:
        if receipt["status"] not in {"COMMITTED", "ALREADY_APPLIED", "INDEX_PENDING", "NO_CHANGE"}:
            return dict(receipt)
        if fail:
            return {**receipt, "status": "INDEX_PENDING", "reason": "index failed; Git commit retained"}
        target = receipt["target_commit"]
        if receipt["owner"] != self.owner or receipt["collection"] != self.collection:
            raise KnowledgeCycleError("receipt identity mismatch")
        self._git(["merge-base", "--is-ancestor", target, self._head()])
        if receipt["status"] != "NO_CHANGE":
            operation_path = "operations/" + sha256(canonical(receipt["operation_id"])) + ".json"
            ledger = json.loads(self._read(target, operation_path))
            if ledger["parent"] != receipt["target_parent"] or ledger["accepted_ids"] != receipt["accepted_ids"]:
                raise KnowledgeCycleError("receipt differs from committed operation")
        entries = [json.loads(self._read(target, path)) for path in self._files(target)
                   if path.startswith("records/")]
        body = {"contract_version": "knowledge-index/v1", "knowledge_commit": target,
                "entries": entries, "revalidation_candidates": revalidation_candidates(entries)}
        self._atomic(self.index_path, canonical(body))
        return {**receipt, "status": "COMMITTED" if receipt["status"] == "INDEX_PENDING" else receipt["status"],
                "index_commit": target, "index_hash": sha256(canonical(body)),
                "reason": "Git snapshot indexed"}

    def retrieve(self, query: str, creator: str, access_scope: str, *, at: str,
                 decisions: Mapping | None = None) -> dict:
        if creator != self.creator or not self.index_path.exists():
            return _trace(query, self, [], "UNAVAILABLE")
        if self.index_path.is_symlink():
            raise KnowledgeCycleError("symlink index forbidden")
        data = json.loads(self.index_path.read_bytes())
        if data["knowledge_commit"] != self.knowledge_commit:
            return _trace(query, self, [], "UNAVAILABLE")
        # Reconstruct from immutable Git; cache contents never confer authority.
        entries = [json.loads(self._read(self.knowledge_commit, path))
                   for path in self._files(self.knowledge_commit) if path.startswith("records/")]
        latest = {}
        for entry in entries:
            key = (entry["origin_instance_id"], entry["record_id"])
            if key not in latest or latest[key]["revision"] < entry["revision"]:
                latest[key] = entry
        revoked = set()
        for entry in latest.values():
            for ref in entry["invalidates"] + entry["supersedes"]:
                revoked.add((ref.get("origin_instance_id", entry["origin_instance_id"]),
                             ref["record_id"], ref["revision"]))
        records = []
        pending = {reference_key(ref) for ref in revalidation_candidates(entries)}
        for entry in latest.values():
            key = (entry["origin_instance_id"], entry["record_id"], entry["revision"])
            if (key in revoked or reference_key(entry) in pending or entry["lifecycle"] != "accepted" or
                entry["creator_id"] != creator or entry["access_scope"] != access_scope or
                (entry["valid_until"] is not None and
                 datetime.fromisoformat(entry["valid_until"].replace("Z", "+00:00")) <=
                 datetime.fromisoformat(at.replace("Z", "+00:00")))):
                continue
            decision = (decisions or {}).get(self._key(entry))
            if not decision:
                continue
            if (set(decision) != {"decision", "reason", "affected"} or
                decision.get("decision") not in {"adopted", "rejected", "revalidate"} or
                not isinstance(decision.get("reason"), str) or not decision["reason"] or
                not isinstance(decision.get("affected"), list) or
                any(not isinstance(v, str) or not v for v in decision["affected"]) or
                (decision["decision"] == "adopted" and not decision["affected"])):
                raise KnowledgeCycleError("reuse requires explicit decision and affected work")
            records.append({"record_id": entry["record_id"], "revision": entry["revision"],
                            "origin_instance_id": entry["origin_instance_id"],
                            "payload_ref": entry["payload_ref"],
                            "content_sha256": entry["content_sha256"],
                            "owner": self.owner, **decision})
        status = "REUSED" if any(r["decision"] == "adopted" for r in records) else "NOT_APPLICABLE"
        if not entries:
            status = "EMPTY_HISTORY"
        return _trace(query, self, records, status)

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


def dispatch(bundles: list[Mapping], providers: Mapping[str, LocalOwner], fail_owner: str | None = None,
             *, payloads: Mapping | None = None, outbox: Path | None = None) -> dict:
    previous = json.loads(outbox.read_bytes()) if outbox and outbox.exists() else {}
    digest = sha256(canonical(bundles))
    if previous and previous.get("bundle_hash") != digest:
        raise KnowledgeCycleError("outbox inputs changed")
    saved = {r["owner"]: r for r in previous.get("receipts", [])}
    parents = previous.get("parents") or {b["owner"]: providers[b["owner"]].knowledge_commit for b in bundles}
    if len({b["owner"] for b in bundles}) != len(bundles):
        raise KnowledgeCycleError("one bundle per owner required")
    receipts = []
    if outbox:
        LocalOwner._atomic(outbox, canonical({"bundle_hash": digest, "parents": parents,
                                            "receipts": list(saved.values())}))
    for bundle in bundles:
        provider = providers[bundle["owner"]]
        prior = saved.get(provider.owner)
        try:
            if not registry()[provider.owner]["write"]:
                result = provider._receipt(bundle, "REJECTED", parents[provider.owner], None,
                                           "parent dispatch write disabled; use catalog-reference capability")
            elif prior and prior["status"] in {"COMMITTED", "ALREADY_APPLIED", "NO_CHANGE"}:
                provider._git(["merge-base", "--is-ancestor", prior["target_commit"], provider._head()])
                if prior["status"] != "NO_CHANGE":
                    operation_path = "operations/" + sha256(canonical(bundle["operation_id"])) + ".json"
                    ledger = json.loads(provider._read(prior["target_commit"], operation_path))
                    if ledger["bundle_hash"] != sha256(canonical(bundle)):
                        raise KnowledgeCycleError("saved receipt does not match bundle")
                result = prior
            elif prior and prior["status"] == "INDEX_PENDING":
                result = provider.index(prior, fail=provider.owner == fail_owner)
            else:
                receipt = provider.commit(bundle, parents[provider.owner],
                                          payloads=(payloads or {}).get(provider.owner))
                try:
                    result = provider.index(receipt, fail=provider.owner == fail_owner)
                except Exception:
                    result = {**receipt, "status": "INDEX_PENDING", "reason": "index failed; commit retained"}
        except Exception:
            result = provider._receipt(bundle, "REJECTED", provider.knowledge_commit, None,
                                       "owner operation unavailable; other receipts retained")
        receipts.append(result)
        saved[provider.owner] = result
        if outbox:
            LocalOwner._atomic(outbox, canonical({"bundle_hash": digest, "parents": parents,
                                                "receipts": list(saved.values())}))
    failed = [r["owner"] for r in receipts if r["status"] in {"REJECTED", "CONFLICT", "INDEX_PENDING"}]
    return {"contract_version":"knowledge-dispatch-report/v1", "status":"PARTIAL" if failed else "COMMITTED",
            "receipts":receipts, "pending_owners":failed}


def operational_payload_valid(record, payload):
    from tools.validate import _schema_errors, load_json
    if record["owner_repository"] != "agentic-art-orchestration" or record["payload_schema"] != "operational-knowledge/v1":
        return False
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return False
    return not _schema_errors(value, load_json(ROOT / "schemas/operational-knowledge.schema.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("registry", "validate", "prepare", "init", "commit", "index", "retrieve"))
    parser.add_argument("--record", type=Path)
    parser.add_argument("--owner")
    parser.add_argument("--collection")
    parser.add_argument("--store", type=Path)
    parser.add_argument("--creator")
    parser.add_argument("--code-commit")
    parser.add_argument("--knowledge-commit")
    parser.add_argument("--operation-id")
    parser.add_argument("--run-id")
    parser.add_argument("--payload-root", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--query", default="")
    parser.add_argument("--at")
    parser.add_argument("--access-scope")
    parser.add_argument("--decisions", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "registry":
            print(json.dumps({"owners": registry()}, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command in {"init", "commit", "index", "retrieve"}:
            if args.owner != "agentic-art-orchestration":
                raise KnowledgeCycleError("use the selected child's native owner CLI")
            if not args.store or not args.store.is_absolute() or not args.creator or not args.collection or not args.code_commit:
                raise KnowledgeCycleError("explicit external store, creator, collection and code commit required")
            if args.store.resolve() == ROOT or ROOT in args.store.resolve().parents:
                raise KnowledgeCycleError("store must be outside the protocol checkout")
            provider = LocalOwner(args.store, args.owner, args.collection, args.code_commit,
                                  args.knowledge_commit, creator=args.creator,
                                  payload_validator=operational_payload_valid)
            if args.command == "init":
                result = {"owner": provider.owner, "collection": provider.collection,
                          "knowledge_commit": provider.knowledge_commit}
            elif args.command == "commit":
                if not args.record or not args.payload_root or not args.operation_id or not args.run_id or not args.knowledge_commit:
                    raise KnowledgeCycleError("commit requires record, payload root, operation, run and expected knowledge commit")
                record = json.loads(args.record.read_bytes())
                validate_record(record, args.owner, args.collection)
                base = args.payload_root.resolve()
                path = base / record["payload_ref"]
                if path.is_symlink() or path.resolve() != path or base not in path.resolve().parents:
                    raise KnowledgeCycleError("payload path escapes selected source")
                bundle = prepare([record], args.owner, args.collection, args.operation_id, args.run_id)
                result = provider.commit(bundle, args.knowledge_commit, payloads={record["payload_ref"]: path.read_bytes()})
            elif args.command == "index":
                if not args.receipt:
                    raise KnowledgeCycleError("index requires receipt")
                result = provider.index(json.loads(args.receipt.read_bytes()))
            else:
                if not args.at or not args.access_scope:
                    raise KnowledgeCycleError("retrieve requires explicit time and access scope")
                decisions = json.loads(args.decisions.read_bytes()) if args.decisions else None
                result = provider.retrieve(args.query, args.creator, args.access_scope, at=args.at, decisions=decisions)
            print(json.dumps(result, sort_keys=True))
            return 2 if result.get("status") in {"REJECTED", "CONFLICT", "UNAVAILABLE"} else 0
        if not args.record or not args.owner or not args.collection:
            raise KnowledgeCycleError("validate requires --record, --owner, and --collection")
        validate_record(json.loads(args.record.read_text(encoding="utf-8")), args.owner, args.collection)
        if args.command == "prepare":
            if not args.operation_id or not args.run_id:
                raise KnowledgeCycleError("prepare requires operation and run identity")
            print(json.dumps(prepare([json.loads(args.record.read_bytes())], args.owner, args.collection,
                                     args.operation_id, args.run_id), sort_keys=True))
            return 0
        print(json.dumps({"status": "PASSED", "record": str(args.record)}, sort_keys=True))
        return 0
    except (KnowledgeCycleError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAILED", "detail": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
