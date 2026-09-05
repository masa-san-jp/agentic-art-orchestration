#!/usr/bin/env python3
"""Validate and bootstrap instance-profile/v1 without implicit identity fallback."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Mapping

import yaml

from tools.validate import _schema_errors, load_json

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/instance-profile.schema.json"
OWNERS = ("self-model-notes", "art-history-notes", "marketing-trends-notes", "agentic-art-research", "agentic-art-production", "viewer-response-notes", "agentic-art-project", "agentic-art-orchestration")

class InstanceProfileError(ValueError): pass

def canonical_bytes(profile: Mapping[str, object]) -> bytes:
    return json.dumps(dict(profile), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def fingerprint(profile: Mapping[str, object]) -> str:
    stable = dict(profile)
    # Entering resume is an operation transition, not a new instance identity.
    stable.pop("mode", None)
    return hashlib.sha256(canonical_bytes(stable)).hexdigest()

def validate_profile(profile: object) -> list[str]:
    errors = _schema_errors(profile, load_json(SCHEMA), "instance-profile")
    if errors or not isinstance(profile, Mapping): return errors
    mode, creator = profile.get("mode"), profile.get("creator_id")
    repos = profile.get("repositories", {})
    if mode == "fork" and not profile.get("upstream_remote"):
        errors.append("instance-profile: fork requires explicit upstream_remote")
    if mode != "resume" and profile.get("origin_instance_id") == profile.get("instance_id"):
        errors.append("instance-profile: a new instance cannot reuse its origin identity")
    for owner in OWNERS:
        entry = repos.get(owner, {}) if isinstance(repos, Mapping) else {}
        if entry.get("knowledge_ref") != f"knowledge/{creator}":
            errors.append(f"instance-profile: {owner} knowledge_ref must belong to active creator")
    permissions = profile.get("permissions", {})
    if permissions.get("remote_write") and mode == "fork" and not profile.get("upstream_remote"):
        errors.append("instance-profile: fork remote write requires an explicit remote")
    if profile.get("delivery_mode") == "public-catalog" and not permissions.get("public_projection"):
        errors.append("instance-profile: public-catalog requires public_projection permission")
    return errors

def load_profile(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    errors = validate_profile(value)
    if errors: raise InstanceProfileError("\n".join(errors))
    return value

def adapt_output_destinations(profile: Mapping[str, object], destinations: Mapping[str, object]) -> dict:
    """Preserve output-destinations/v1 while applying the explicit instance delivery policy."""
    result = dict(destinations)
    roots = dict(result.get("destinations", {}))
    if profile["delivery_mode"] == "internal": roots.pop("public_projection_root", None)
    elif "public_projection_root" not in roots: raise InstanceProfileError("public-catalog requires public_projection_root")
    result["destinations"] = roots
    return result

def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    if result.returncode: raise InstanceProfileError(result.stderr.strip() or "local git operation failed")
    return result.stdout.strip()

def bootstrap(profile: Mapping[str, object], local_stores: Mapping[str, Path], state_root: Path) -> dict:
    errors = validate_profile(profile)
    if errors: raise InstanceProfileError("\n".join(errors))
    missing = sorted(set(OWNERS) - set(local_stores))
    if missing: raise InstanceProfileError(f"local store mapping missing: {missing}")
    marker = state_root / "instances" / str(profile["instance_id"]) / "instance-resolution.json"
    if marker.exists():
        existing = json.loads(marker.read_text())
        if existing["profile_fingerprint"] != fingerprint(profile): raise InstanceProfileError("saved identity conflicts with selected profile")
        return existing
    if profile["mode"] == "resume": raise InstanceProfileError("resume requires a saved instance-resolution")
    knowledge_refs, code_refs = {}, {}
    for owner in OWNERS:
        store = Path(local_stores[owner]).resolve()
        store.mkdir(parents=True, exist_ok=True)
        if not (store / ".git").exists():
            _git(store, "init", "-b", "knowledge")
            _git(store, "config", "user.name", "agentic-art-instance")
            _git(store, "config", "user.email", "local@agentic-art.invalid")
            (store / ".gitignore").write_text("runtime/\nraw/\ncredentials/\n", encoding="utf-8")
            _git(store, "add", ".gitignore")
            _git(store, "commit", "-m", "Initialize local knowledge store")
        knowledge_refs[owner] = {"store_id": profile["repositories"][owner]["knowledge_store_id"], "ref": profile["repositories"][owner]["knowledge_ref"], "commit": _git(store, "rev-parse", "HEAD")}
        code_refs[owner] = {"repository": profile["repositories"][owner]["code_repository"], "commit": profile["repositories"][owner]["code_commit"]}
    result = {"contract_version":"instance-resolution/v1", "profile_fingerprint":fingerprint(profile), "instance_id":profile["instance_id"], "creator_id":profile["creator_id"], "mode":profile["mode"], "personalization_status":"UNMET_PUBLIC_SEED_ONLY" if profile["personalization_mode"] == "public-seed-only" else "SATISFIED", "code_refs":code_refs, "knowledge_refs":knowledge_refs}
    marker.parent.mkdir(parents=True, exist_ok=True); marker.write_text(json.dumps(result, sort_keys=True, indent=2)+"\n")
    return result

def migration_plan(saved: Mapping[str, object], candidate: Mapping[str, object]) -> dict:
    """Return a non-mutating split of code and knowledge changes."""
    return {"dry_run": True, "identity_preserved": saved.get("creator_id") == candidate.get("creator_id"), "code_updates": {k:v for k,v in candidate.get("code_refs",{}).items() if saved.get("code_refs",{}).get(k) != v}, "knowledge_updates": {k:v for k,v in candidate.get("knowledge_refs",{}).items() if saved.get("knowledge_refs",{}).get(k) != v}}
