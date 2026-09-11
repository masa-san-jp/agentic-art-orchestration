#!/usr/bin/env python3
"""Validate and bootstrap instance-profile/v1 without implicit identity fallback."""
from __future__ import annotations

import hashlib
import json
import subprocess
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.path_safety import external_path as _safe_external_path

import yaml

from tools.validate import _schema_errors, load_json

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
    if mode == "fork" and not profile.get("fork_remote"):
        errors.append("instance-profile: fork requires explicit user-owned fork_remote")
    if mode != "resume" and profile.get("origin_instance_id") == profile.get("instance_id"):
        errors.append("instance-profile: a new instance cannot reuse its origin identity")
    for owner in OWNERS:
        entry = repos.get(owner, {}) if isinstance(repos, Mapping) else {}
        if entry.get("knowledge_ref") != f"knowledge/{creator}":
            errors.append(f"instance-profile: {owner} knowledge_ref must belong to active creator")
    permissions = profile.get("permissions", {})
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
    from tools.output_destinations import validate_destination_profile
    # Repo-local Project delivery deliberately allows the state and internal
    # roots to live below the Project checkout.  That overlap is forbidden by
    # output-destinations/v1, so v2 is validated by its own closed schema and
    # handled by the repo-local resolver in _bootstrap below.
    if isinstance(destinations, Mapping) and destinations.get("contract_version") == "output-destinations/v2":
        errors = validate_profile(profile) + _schema_errors(
            destinations,
            load_json(ROOT / "schemas/output-destinations-v2.schema.json"),
            "output-destinations/v2",
        )
        if profile.get("delivery_mode") != "public-catalog" or not profile.get("permissions", {}).get("public_projection"):
            errors.append("output-destinations/v2 requires public-catalog with public_projection permission")
        if errors:
            raise InstanceProfileError("\n".join(errors))
        return dict(destinations)
    errors = validate_profile(profile) + validate_destination_profile(destinations)
    if errors:
        raise InstanceProfileError("\n".join(errors))
    result = dict(destinations)
    roots = dict(result.get("destinations", {}))
    if profile["delivery_mode"] == "internal": roots.pop("public_projection_root", None)
    elif "public_projection_root" not in roots: raise InstanceProfileError("public-catalog requires public_projection_root")
    result["destinations"] = roots
    return result

def _git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, env=env)
    if result.returncode: raise InstanceProfileError("local git operation failed: " + args[0])
    return result.stdout.strip()


PINNED_MARKER = ".agentic-art-pinned-workspace.json"


def _pinned_checkout_dirty(path: Path) -> bool:
    """Treat only the tool-owned immutable workspace marker as clean metadata."""
    status = _git(path, "status", "--porcelain", "--untracked-files=all")
    unexpected = [line for line in status.splitlines() if line and line not in {f"?? {PINNED_MARKER}"}]
    return bool(unexpected)

def _external(value: object) -> Path:
    try:
        path = _safe_external_path(value)
    except ValueError as exc:
        raise InstanceProfileError(str(exc).replace("EXPLICIT_NONSYMLINK_PATH_REQUIRED", "absolute non-symlink local path required")) from exc
    if path == ROOT or ROOT in path.parents or path in ROOT.parents:
        raise InstanceProfileError("local state/store must be outside protocol checkout")
    return path


def _save(path: Path, value: Mapping) -> None:
    from tools.knowledge_cycle import LocalOwner
    if path.is_symlink():
        raise InstanceProfileError("symlink state forbidden")
    path.parent.mkdir(parents=True, exist_ok=True)
    LocalOwner._atomic(path, canonical_bytes(value))


def _bootstrap(profile: Mapping[str, object], local_config: Mapping, state_root: Path,
              *, run_id: str = "setup", dry_run: bool = False, owner_initializers=None) -> dict:
    """Resolve a recorded setup and pin each run without modifying user checkouts.

    Local config is external and explicit: stores are keyed by knowledge_store_id,
    code_sources by code_repository, and collections by source collection ID.
    No remote operation is performed, including when remote_write is permitted.
    """
    from tools.knowledge_cycle import LocalOwner
    from tools.pinned_workspace import materialize_pinned_workspace
    errors = validate_profile(profile)
    if errors: raise InstanceProfileError("\n".join(errors))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", run_id):
        raise InstanceProfileError("invalid run ID")
    if not isinstance(local_config, Mapping):
        raise InstanceProfileError("SETUP_REQUIRED: local config missing")
    errors = _schema_errors(local_config, load_json(ROOT / "schemas/instance-local-config.schema.json"), "local-config")
    if errors:
        raise InstanceProfileError("\n".join(errors))
    state_root = _external(state_root)
    base = state_root / "instances" / str(profile["instance_id"])
    _external(base)
    setup_path = base / "setup.json"
    marker = base / "runs" / run_id / "instance-resolution.json"
    _external(marker.parent)
    stable = {k: profile.get(k) for k in ("instance_id", "creator_id", "origin_instance_id", "fork_remote")}
    stable["stores"] = {owner: {k: profile["repositories"][owner][k] for k in
                               ("knowledge_store_id", "knowledge_ref", "source_collections")}
                        for owner in OWNERS}
    stable["permissions"] = profile["permissions"]
    stable["personalization_mode"] = profile["personalization_mode"]
    stable["delivery_mode"] = profile["delivery_mode"]
    stable["source_attributions"] = {c: local_config.get("collections", {}).get(c) for entry in
                                     profile["repositories"].values() for c in entry["source_collections"]}
    saved_setup = json.loads(setup_path.read_text()) if setup_path.exists() else None
    if saved_setup and saved_setup["identity"] != stable:
        raise InstanceProfileError("saved identity, consent or collection conflicts with selected profile")
    if profile["mode"] == "resume" and not saved_setup:
        raise InstanceProfileError("SETUP_REQUIRED: resume requires saved setup")
    stores, sources, paths = {}, {}, [state_root]
    for owner in OWNERS:
        entry = profile["repositories"][owner]
        store_id = entry["knowledge_store_id"]
        binding = local_config.get("stores", {}).get(store_id)
        if not isinstance(binding, Mapping) or any(binding.get(k) != v for k, v in
                {"owner": owner, "creator_id": profile["creator_id"],
                 "instance_id": profile["instance_id"], "knowledge_ref": entry["knowledge_ref"]}.items()):
            raise InstanceProfileError("SETUP_REQUIRED: store binding identity mismatch")
        store = _external(binding.get("path"))
        stores[owner] = store
        paths.append(store)
        identity = {"owner": owner, "collection": store_id, "creator": profile["creator_id"]}
        store_marker = store / "store.json"
        if store_marker.exists():
            if not saved_setup or store_marker.is_symlink() or json.loads(store_marker.read_text()) != identity:
                raise InstanceProfileError("refuse adoption of another instance knowledge store")
        elif store.exists() and any(store.iterdir()):
            raise InstanceProfileError("refuse populated unregistered store")
        elif not all(profile["permissions"][k] for k in ("local_knowledge_write", "local_git_commit")):
            raise InstanceProfileError("local knowledge initialization permission denied")
        for collection in entry["source_collections"]:
            grant = local_config.get("collections", {}).get(collection)
            if not isinstance(grant, Mapping) or profile["creator_id"] not in grant.get("readers", []):
                raise InstanceProfileError("source collection read permission missing")
            if not grant.get("origin_instance_id") or not grant.get("creator_id"):
                raise InstanceProfileError("source collection attribution missing")
        code = local_config.get("code_sources", {}).get(entry["code_repository"])
        if not isinstance(code, Mapping) or entry["code_commit"] not in code.get("qualified_commits", []):
            raise InstanceProfileError("qualified code pin evidence missing")
        # Code sources are read-only inputs; the running protocol checkout is
        # valid here. Only state/store destinations must be outside it.
        try:
            source = _safe_external_path(code.get("path"), require_exists=True)
        except ValueError as exc:
            raise InstanceProfileError("explicit nonsymlink code source required") from exc
        if _git(source, "rev-parse", "--show-toplevel") != str(source):
            raise InstanceProfileError("code source must be an explicit repository root")
        _git(source, "cat-file", "-e", entry["code_commit"] + "^{commit}")
        sources[owner] = source
    repo_local_project_root = None
    if local_config.get("output_destinations", {}).get("contract_version") == "output-destinations/v2":
        repo_local_project_root = _external(local_config["output_destinations"]["project_root"])
    for index, path in enumerate(paths):
        if any(path == other or path in other.parents or other in path.parents for other in paths[index + 1:]):
            raise InstanceProfileError("local store/state paths overlap")
        overlapping_sources = [source for source in sources.values()
            if path == source or path in source.parents or source in path.parents]
        if repo_local_project_root is not None and path == state_root and any(source == repo_local_project_root for source in overlapping_sources):
            # v2 intentionally keeps ignored runtime state under the selected
            # Project checkout.  The pinned code checkout is still materialized
            # separately below, so the tracked Project tree is never modified.
            overlapping_sources = [source for source in overlapping_sources if source != repo_local_project_root]
        if overlapping_sources:
            raise InstanceProfileError("knowledge/state and code paths overlap")
    from tools.output_destinations import resolve_destinations
    destinations = adapt_output_destinations(profile, local_config.get("output_destinations", {}))
    if destinations.get("contract_version") == "output-destinations/v2":
        from tools.repo_local_destinations import resolve_project_root
        project_root = _external(destinations["project_root"])
        relative_state = destinations["destinations"]["state_root"]
        resolved_state = (project_root / relative_state).resolve()
        if resolved_state != state_root.resolve():
            raise InstanceProfileError("repo-local output state root must match explicit instance state root")
        destination_evidence = resolve_project_root(project_root, run_id=run_id)
    else:
        try:
            configured_state_root = _safe_external_path(destinations["destinations"].get("state_root"))
        except ValueError as exc:
            raise InstanceProfileError("output state root must be an explicit non-symlink path") from exc
        if configured_state_root != state_root:
            raise InstanceProfileError("output state root must match explicit instance state root")
        destination_evidence = resolve_destinations(direct=destinations["destinations"], environment={},
            repository_root=ROOT, child_roots=list(stores.values()) + list(sources.values()), run_id=run_id)
    bindings = {owner: str(path) for owner, path in stores.items()}
    bindings["output_destinations"] = destinations
    if saved_setup and saved_setup["bindings"] != bindings:
        raise InstanceProfileError("saved local store mapping changed")
    if marker.exists():
        existing = json.loads(marker.read_text())
        errors = _schema_errors(existing, load_json(ROOT / "schemas/instance-resolution.schema.json"), "saved-resolution")
        if errors or any(existing.get(k) != profile[k] for k in ("instance_id", "creator_id")):
            raise InstanceProfileError("invalid saved resolution identity or schema")
        if existing["profile_fingerprint"] != fingerprint(profile):
            raise InstanceProfileError("same run cannot change code/profile snapshot; use a new run")
        for owner, ref in existing["knowledge_refs"].items():
            entry = profile["repositories"][owner]
            if existing["code_refs"][owner] != {"repository": entry["code_repository"], "commit": entry["code_commit"]} or ref["ref"] != entry["knowledge_ref"]:
                raise InstanceProfileError("saved refs conflict with selected profile")
            LocalOwner(stores[owner], owner, ref["store_id"], existing["code_refs"][owner]["commit"],
                       ref["commit"], creator=str(profile["creator_id"]), payload_validator=lambda *_: False)
            checkout = marker.parent / "code" / owner
            if _git(checkout, "rev-parse", "HEAD") != existing["code_refs"][owner]["commit"] or _pinned_checkout_dirty(checkout):
                raise InstanceProfileError("saved isolated code checkout changed")
        return existing
    if dry_run:
        return {"dry_run": True, "identity_preserved": True,
                "code_refs": {o: profile["repositories"][o]["code_commit"] for o in OWNERS},
                "knowledge_store_ids": {o: profile["repositories"][o]["knowledge_store_id"] for o in OWNERS}}
    # Record setup before writes so a partial bootstrap can be resumed without adoption.
    if not saved_setup:
        _save(setup_path, {"identity": stable, "bindings": bindings})
    knowledge_refs, code_refs = {}, {}
    for owner in OWNERS:
        entry = profile["repositories"][owner]
        code_refs[owner] = {"repository": entry["code_repository"], "commit": entry["code_commit"]}
        checkout = marker.parent / "code" / owner
        if checkout.exists():
            if _git(checkout, "rev-parse", "HEAD") != entry["code_commit"] or _pinned_checkout_dirty(checkout):
                raise InstanceProfileError("interrupted code checkout requires inspection")
        else:
            # Existing canonical helper isolates dirty/diverged sources at qualified pins.
            staging_destination = marker.parent / "staging" / owner
            temporary_staging = None
            if repo_local_project_root is not None and sources[owner] == repo_local_project_root:
                # The Project checkout is both a code source and the v2 output
                # root.  Clone its pinned code through an external temporary
                # directory so the pinned-workspace overlap guard remains
                # intact and no recursive copy enters .agentic-art/.
                staging_parent = repo_local_project_root.parent.parent
                try:
                    temporary_staging = Path(tempfile.mkdtemp(
                        prefix=f".agentic-art-bootstrap-{profile['instance_id']}-", dir=str(staging_parent)))
                except OSError:
                    # A checkout directly below a protected filesystem root
                    # may not permit a sibling there; the default temp dir is
                    # safe as long as it is not an ancestor of the source.
                    temporary_staging = Path(tempfile.mkdtemp(
                        prefix=f".agentic-art-bootstrap-{profile['instance_id']}-"))
                source_parent = sources[owner].parent.resolve()
                if source_parent == temporary_staging or source_parent in temporary_staging.parents or temporary_staging in source_parent.parents:
                    raise InstanceProfileError("cannot allocate non-overlapping code staging workspace")
                staging_destination = temporary_staging
            materialize_pinned_workspace({"repositories": [{"id": owner, "path": sources[owner].name,
                "observed_commit": entry["code_commit"]}]}, sources[owner].parent,
                staging_destination)
            checkout.parent.mkdir(parents=True, exist_ok=True)
            (staging_destination / sources[owner].name).rename(checkout)
            if temporary_staging is not None:
                (staging_destination / PINNED_MARKER).unlink(missing_ok=True)
                staging_destination.rmdir()
        initializer = (owner_initializers or {}).get(owner)
        provider = LocalOwner(stores[owner], owner, entry["knowledge_store_id"], entry["code_commit"],
            creator=str(profile["creator_id"]), payload_validator=lambda *_: False,
            initializer=(lambda path, init=initializer, pin=checkout: init(path, pin)) if initializer else None)
        knowledge_refs[owner] = {"store_id": entry["knowledge_store_id"], "ref": entry["knowledge_ref"], "commit": provider.knowledge_commit}
    result = {"contract_version":"instance-resolution/v1", "profile_fingerprint":fingerprint(profile), "instance_id":profile["instance_id"], "creator_id":profile["creator_id"], "mode":profile["mode"], "personalization_status":"UNMET_PUBLIC_SEED_ONLY" if profile["personalization_mode"] == "public-seed-only" else "SATISFIED", "code_refs":code_refs, "knowledge_refs":knowledge_refs}
    result["projection_status"] = "SKIPPED" if profile["delivery_mode"] == "internal" else "NOT_RUN"
    result["destination_resolution"] = destination_evidence
    result["source_collections"] = stable["source_attributions"]
    errors = _schema_errors(result, load_json(ROOT / "schemas/instance-resolution.schema.json"), "instance-resolution")
    if errors:
        raise InstanceProfileError("\n".join(errors))
    _save(marker, result)
    return result


def bootstrap(profile: Mapping[str, object], local_config: Mapping, state_root: Path,
              *, run_id: str = "setup", dry_run: bool = False, owner_initializers=None) -> dict:
    """Preflight without writes, then serialize bootstrap and recheck under the lock."""
    import fcntl
    preview = _bootstrap(profile, local_config, state_root, run_id=run_id, dry_run=True, owner_initializers=owner_initializers)
    if dry_run:
        return preview
    root = _external(state_root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "instance-bootstrap.lock"
    if lock.is_symlink():
        raise InstanceProfileError("symlink lock forbidden")
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InstanceProfileError("another instance bootstrap holds the state lock") from exc
        return _bootstrap(profile, local_config, root, run_id=run_id, owner_initializers=owner_initializers)

def migration_plan(saved: Mapping[str, object], candidate: Mapping[str, object]) -> dict:
    """Return a non-mutating split of code and knowledge changes."""
    if any(saved.get(k) != candidate.get(k) for k in ("instance_id", "creator_id")):
        raise InstanceProfileError("migration cannot change identity")
    return {"dry_run": True, "identity_preserved": True, "code_updates": {k:v for k,v in candidate.get("code_refs",{}).items() if saved.get("code_refs",{}).get(k) != v}, "knowledge_updates": {k:v for k,v in candidate.get("knowledge_refs",{}).items() if saved.get("knowledge_refs",{}).get(k) != v}}
