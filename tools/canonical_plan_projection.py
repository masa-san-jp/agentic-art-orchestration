"""Production-owned attestation boundary and exact-byte projection/v2 transaction."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import os
import re
import subprocess
import sys
import time
import yaml


# Production's attestation CLI is a local subprocess; a slow disk or a busy
# machine can make one call time out.  Retry those, never a verdict.
ATTESTATION_ATTEMPTS = 3
ATTESTATION_TIMEOUT_SECONDS = 120
# Statuses of ensure_automatic_attestation that must stop before projection.
ATTESTATION_BLOCKED = frozenset({"REJECTED", "UNAVAILABLE"})
# What an agent does next for each blocked status (run.py and knowledge_cycle_run.py).
ATTESTATION_UNAVAILABLE_ACTION = (
    "Production's attestation CLI did not answer after bounded retries; check that the pinned "
    "Production checkout and its interpreter start, then resume the identical run.")
ATTESTATION_REJECTED_ACTION = (
    "Repair the reported Production plan, renderer, asset, or provenance finding and resume "
    "the identical run.")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_fields(plan, code):
    """Report opaque owner provenance; never create review or attest approval."""
    plan, code = Path(plan).resolve(), Path(code).resolve()
    result = {"plan": str(plan), "production_code_root": str(code)}
    path = plan.with_name("public-plan-attestation.json")
    if path.is_file() and not path.is_symlink():
        raw = path.read_bytes()
        document = json.loads(raw)
        result.update(public_plan_attestation=str(path),
                      public_plan_attestation_sha256=digest(raw),
                      source_identity=document["project_id"]+"#"+document["plan_id"],
                      plan_revision=document["plan_revision"])
    return result


def _backoff(seconds):
    time.sleep(seconds)


class _OwnerUnavailable(Exception):
    """Production's CLI did not answer within the bounded attempts."""


def _owner_cli(command, code, *, attempts, sleep):
    """Run one Production CLI call, retrying only a timeout or an OS error.

    A non-zero exit is the owner's verdict and is returned as is; only a call
    that produced no verdict is retried, with 1 s, 2 s, ... backoff.
    """
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return subprocess.run(command, cwd=code, capture_output=True, text=True,
                                  timeout=ATTESTATION_TIMEOUT_SECONDS)
        except (subprocess.TimeoutExpired, OSError) as exc:
            last = exc
            if attempt < attempts:
                sleep(2 ** (attempt - 1))
    raise _OwnerUnavailable(type(last).__name__)


def _retire_attestation(existing, superseded_root):
    """Set a stale attestation aside, byte for byte; never edit or lose it.

    Production's writer is create-only: a different existing file is
    ATTESTATION_CONFLICT, and its contract has no replace mode.  The stale file
    no longer verifies, so it is kept under the run's state, named by its own
    hash, and the canonical path is left empty for the sanctioned
    ``--automatic-plan`` generation to write a fresh one.

    The copy is made in the destination directory (a temporary file, fsynced,
    then renamed into place), so a state root on another filesystem never
    holds a partial file.  The original is unlinked only after the kept copy
    is read back with the original's digest, and only if the original did not
    change meanwhile; otherwise an OSError leaves the original where it was.
    """
    symlink = existing.is_symlink()
    raw = _retirement_bytes(existing, symlink)
    sha = digest(raw)
    name = ("symlink-" if symlink else "public-plan-attestation.") + sha + ".json"
    destination = Path(superseded_root) / existing.parent.parent.name / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not _kept_copy_matches(destination, symlink, sha):
        # Content-addressed: an earlier retirement may already hold these
        # bytes; anything else under this name is replaced by a full copy.
        temporary = destination.with_name("." + name + "." + str(os.getpid()) + ".tmp")
        try:
            if symlink:
                os.symlink(raw.decode("utf-8", "surrogateescape"), temporary)
            else:
                with open(temporary, "xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.is_symlink() or temporary.exists():
                temporary.unlink()
        _fsync_directory(destination.parent)
        if not _kept_copy_matches(destination, symlink, sha):
            raise OSError("retired attestation copy does not match the original digest")
    if existing.is_symlink() != symlink or digest(_retirement_bytes(existing, symlink)) != sha:
        raise OSError("attestation changed while it was being retired")
    existing.unlink()
    _fsync_directory(existing.parent)
    return {"path": str(destination), "sha256": sha}


def _retirement_bytes(path, symlink):
    return os.readlink(path).encode("utf-8", "surrogateescape") if symlink else path.read_bytes()


def _kept_copy_matches(destination, symlink, sha):
    if destination.is_symlink() != symlink or not (symlink or destination.is_file()):
        return False
    return digest(_retirement_bytes(destination, symlink)) == sha


def _fsync_directory(directory):
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _stale_reason(existing, plan, producer_commit):
    """Say why an existing attestation cannot be reused, or None if it might be."""
    if existing.is_symlink() or not existing.is_file():
        return "ATTESTATION_NOT_A_FILE"
    try:
        current = json.loads(existing.read_bytes())
        if current["human_plan"]["sha256"] != "sha256:" + digest(plan.read_bytes()):
            return "PLAN_BYTES_CHANGED"
        if current["producer"]["commit"] != producer_commit:
            return "PRODUCER_COMMIT_CHANGED"
    except (ValueError, KeyError, TypeError, OSError):
        return "ATTESTATION_UNREADABLE"
    return None


RECORD_PATH = re.compile(r"plans/P[0-9]{4}-[a-z0-9]+(?:-[a-z0-9]+)*")


def published_record(target, identity, revision, body_hash):
    """Return the receiver's record for these exact plan bytes, or None.

    A record that the public target already holds for the same source
    identity, the same plan_revision and the same plan.md bytes needs nothing
    new: a later producer commit that renders identical bytes is a no-op, not
    a new revision.  Anything unreadable or unexpected is simply "not
    published"; the normal owner-verified path then decides.
    """
    if target is None or not isinstance(identity, str) or not isinstance(revision, int):
        return None
    try:
        index = yaml.safe_load((Path(target) / "plans/index.yaml").read_text(encoding="utf-8"))
        records = index.get("records") if isinstance(index, dict) else None
        for record in records if isinstance(records, list) else []:
            if (isinstance(record, dict) and record.get("source_identity") == identity
                    and str(record.get("plan_revision")) == str(revision)
                    and record.get("content_sha256") == body_hash
                    and RECORD_PATH.fullmatch(str(record.get("path", "")))):
                return record
    except (OSError, ValueError, yaml.YAMLError, AttributeError):
        return None
    return None


def _public_record_files(target, record, project, body):
    """Return ``(attestation, files)`` when a public record equals the internal plan.

    Equal means: the public plan.md is ``body``, the public attestation is the
    one the index names, and every medium that attestation lists has its
    attested hash both in the record and under the internal ``project``.
    Plan bytes alone are not enough: a re-rendered medium changes the
    attested content even when plan.md is identical.  Raises only for
    unreadable input; callers treat that as "not equal".
    """
    directory = Path(target) / record["path"]
    plan_path, attestation_path = directory / "plan.md", directory / "public-plan-attestation.json"
    if any(path.is_symlink() or not path.is_file() for path in (plan_path, attestation_path)):
        return None
    public_body, raw = plan_path.read_bytes(), attestation_path.read_bytes()
    if public_body != body or digest(raw) != record.get("attestation_sha256"):
        return None
    attestation = json.loads(raw)
    files = {"plan.md": body, "public-plan-attestation.json": raw}
    for asset in attestation.get("assets", []):
        relative = asset["path"]
        if not relative.startswith("03_plan/media/") or ".." in Path(relative).parts:
            return None
        public_media, internal_media = directory / relative[8:], Path(project) / relative
        if any(path.is_symlink() or not path.is_file() for path in (public_media, internal_media)):
            return None
        data = public_media.read_bytes()
        if "sha256:" + digest(data) != asset["sha256"] or internal_media.read_bytes() != data:
            return None
        files[relative[8:]] = data
    return attestation, files


def _published_bundle(item, internal, target):
    try:
        return _published_bundle_or_none(item, internal, target)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _published_bundle_or_none(item, internal, target):
    """Reuse an already projected record whose plan bytes did not change.

    The bundle carries the receiver's existing public attestation, commit and
    media, so the transaction writes nothing and ends ALREADY_PROJECTED.  The
    internal plan and every attested medium must still equal the public bytes;
    otherwise None is returned and the owner-verified path runs.
    """
    source = Path(str(item.get("plan", "")))
    if (not source.is_absolute() or source.resolve() != source or internal not in source.parents
            or source.name != "production-plan.md" or not source.is_file()):
        return None
    body = source.read_bytes()
    if digest(body) != item.get("production_plan_markdown_sha256", item.get("production_plan_sha256")):
        return None
    record = published_record(target, item.get("source_identity"), item.get("plan_revision"), digest(body))
    if record is None:
        return None
    matched = _public_record_files(target, record, source.parent.parent, body)
    if matched is None:
        return None
    attestation, files = matched
    return {"identity": record["source_identity"], "revision": int(record["plan_revision"]), "body_hash": digest(body),
            "attestation_hash": record["attestation_sha256"], "production_commit": record["production_commit"],
            "production_state": record.get("production_state"), "assets": attestation.get("assets", []),
            "files": files, "reused_public_record": record["id"]}


def _already_published(existing, plan, project, target):
    """The receiver's record when it already holds these plan bytes and media."""
    try:
        current = json.loads(existing.read_bytes())
        body = plan.read_bytes()
        record = published_record(target, f'{current.get("project_id")}#{current.get("plan_id")}',
                                  current.get("plan_revision"), digest(body))
        if record is None or _public_record_files(target, record, project, body) is None:
            return None
        return record
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def ensure_automatic_attestation(*, python, code, project, producer_commit, generated_at,
                                 superseded_root=None, attempts=ATTESTATION_ATTEMPTS, sleep=None,
                                 public_projection_root=None):
    """Run Production's closed AUTOMATIC_PLAN attestation before projection.

    This is the mechanical owner check for a canonical plan record: no human
    approval, no external effect.  An attestation that the pinned owner still
    verifies for the identical plan bytes and producer commit is reused, so a
    resumed run (with a new clock) does not collide with its own earlier file.

    An existing attestation for other plan bytes, another producer commit, or
    one the owner's ``--check`` no longer verifies is stale.  With
    ``superseded_root`` it is retired (see ``_retire_attestation``) and the
    plan is attested again through the same sanctioned command; without it the
    result is REJECTED with ``ATTESTATION_STALE`` instead of the owner's
    conflict.  A CLI call that times out or cannot start is retried up to
    ``attempts`` times; if none answers, the result is UNAVAILABLE with a
    finding.  This function never raises for those cases.

    When only the producer commit changed, the plan bytes and every attested
    medium are identical and ``public_projection_root`` already holds a record
    for them at the same plan_revision, nothing is re-attested
    (ALREADY_PUBLISHED): the projection keeps that record and its public
    attestation.  A changed medium is re-attested like changed plan bytes.
    """
    # Resolve before running with cwd=code, so a relative --production-root
    # does not name the tool (or the project) twice.
    code, project = Path(code).resolve(), Path(project).resolve()
    sleep = sleep or _backoff
    tool = str(code / "tools/public_plan_attestation.py")
    command = [str(python), tool, "--project-root", str(project), "--automatic-plan",
               "--producer-commit", str(producer_commit), "--generated-at", str(generated_at)]
    existing = project / "03_plan/public-plan-attestation.json"
    plan = project / "03_plan/production-plan.md"
    retired = None
    try:
        if (existing.exists() or existing.is_symlink()) and plan.is_file():
            reason = _stale_reason(existing, plan, producer_commit)
            if reason is None:
                checked = _owner_cli([str(python), tool, "--project-root", str(project), "--check"], code,
                                     attempts=attempts, sleep=sleep)
                try:
                    verified = checked.returncode == 0 and json.loads(checked.stdout).get("status") == "VERIFIED"
                except (ValueError, AttributeError):
                    verified = False
                if verified:
                    return {"status": "ALREADY_ATTESTED", "command": command}
                reason = "CHECK_FAILED"
            if reason == "PRODUCER_COMMIT_CHANGED" and public_projection_root is not None:
                record = _already_published(existing, plan, project, public_projection_root)
                if record is not None:
                    return {"status": "ALREADY_PUBLISHED", "command": command, "public_record": record["id"]}
            if superseded_root is None:
                return {"status": "REJECTED", "command": command,
                        "finding": {"status": "REJECTED", "reason": "ATTESTATION_STALE: " + reason}}
            try:
                retired = dict(_retire_attestation(existing, superseded_root), reason=reason)
            except OSError as exc:
                return {"status": "REJECTED", "command": command,
                        "finding": {"status": "REJECTED", "reason": "ATTESTATION_RETIRE_FAILED: " + type(exc).__name__}}
        result = _owner_cli(command, code, attempts=attempts, sleep=sleep)
    except _OwnerUnavailable as exc:
        unavailable = {"status": "UNAVAILABLE", "command": command, "attempts": attempts,
                       "finding": {"status": "UNAVAILABLE",
                                   "reason": f"{exc}: Production attestation CLI did not answer in {attempts} attempts"}}
        if retired is not None:
            unavailable["retired"] = retired
        return unavailable
    outcome = {"command": command}
    if retired is not None:
        outcome["retired"] = retired
    if result.returncode:
        try:
            finding = json.loads(result.stdout)
        except ValueError:
            finding = {"status": "REJECTED", "reason": result.stderr.strip() or "automatic attestation failed"}
        return {"status": "REJECTED", "finding": finding, **outcome}
    return {"status": "REATTESTED" if retired is not None else "ATTESTED", **outcome}


def _failure_reason(exc):
    """Name why projection stopped without copying paths, bytes or secrets.

    Only the fixed messages raised by this module are kept verbatim; anything
    raised elsewhere (YAML/JSON parsers, the filesystem, owner CLIs) is reduced
    to its exception type.
    """
    trace = exc.__traceback__
    while trace is not None and trace.tb_next is not None:
        trace = trace.tb_next
    message = str(exc)
    if (type(exc) is ValueError and trace is not None and trace.tb_frame.f_code.co_filename == __file__
            and re.fullmatch(r"[A-Za-z0-9_ ./-]{1,120}", message)):
        return message
    return type(exc).__name__


def _owner_bundle(item, internal, child_python=None):
    from tools import public_projection as p
    code = Path(str(item.get("production_code_root", "")))
    sha = item.get("production_source_commit")
    if not code.is_absolute() or code.resolve() != code or not isinstance(sha,str) or not p.SHA40.fullmatch(sha):
        raise ValueError("qualified Production code checkout required")
    if subprocess.check_output(["git","-C",str(code),"rev-parse","HEAD"],text=True).strip()!=sha or subprocess.check_output(["git","-C",str(code),"status","--porcelain"]):
        raise ValueError("Production code pin/cleanliness mismatch")
    source = Path(str(item.get("plan", "")))
    if not source.is_absolute() or source.resolve()!=source or internal not in source.parents or source.name!="production-plan.md":
        raise ValueError("canonical internal plan locator required")
    attestation_path = Path(str(item.get("public_plan_attestation", "")))
    if attestation_path != source.with_name("public-plan-attestation.json") or attestation_path.resolve()!=attestation_path:
        raise ValueError("explicit canonical attestation locator required")
    body, raw = source.read_bytes(), attestation_path.read_bytes()
    if digest(body)!=item.get("production_plan_markdown_sha256", item.get("production_plan_sha256")) or digest(raw)!=item.get("public_plan_attestation_sha256"):
        raise ValueError("source body/attestation hash mismatch")
    project = source.parent.parent
    # A pinned child checkout is not required to carry a virtualenv.  The
    # orchestrator already selected the qualified interpreter for every child
    # command, so reuse it for the owner-side attestation check.  Keep the
    # legacy fallback for direct callers and existing fixture tests.
    validator_python = str(child_python) if child_python else str(code / ".venv/bin/python")
    if child_python is None and not Path(validator_python).is_file():
        validator_python = sys.executable
    command=[validator_python,"tools/public_plan_attestation.py","--project-root",str(project),"--check"]
    if item.get("require_native_review") is True:
        command.append("--require-native-review")
    checked=subprocess.run(command,cwd=code,capture_output=True,text=True,timeout=120)
    response=json.loads(checked.stdout) if checked.returncode==0 else {}
    if checked.returncode or response.get("status")!="VERIFIED" or not isinstance(response.get("production_state"),str) or not response["production_state"]:
        raise ValueError("pinned Production validator rejected attestation")
    # Only the owner CLI interprets its schema, integrity, coverage and renderer.
    a=json.loads(raw)
    if a["producer"]["commit"]!=sha or a["producer"]["repository"]!="masa-san-jp/agentic-art-production" or a["human_plan"]["sha256"]!="sha256:"+digest(body):
        raise ValueError("owner provenance mismatch")
    identity=a["project_id"]+"#"+a["plan_id"]
    if identity!=item.get("source_identity") or a["plan_revision"]!=item.get("plan_revision"):
        raise ValueError("source identity/revision mismatch")
    files={"plan.md":body,"public-plan-attestation.json":raw}
    for asset in a["assets"]:
        relative=asset["path"]
        if not relative.startswith("03_plan/media/") or ".." in Path(relative).parts:
            raise ValueError("owner asset does not fit receiver layout")
        target=project/relative
        if target.resolve()!=target:raise ValueError("asset symlink rejected")
        data=target.read_bytes()
        if "sha256:"+digest(data)!=asset["sha256"]:raise ValueError("asset changed after owner validation")
        files[relative[8:]]=data
    if source.read_bytes()!=body or attestation_path.read_bytes()!=raw:
        raise ValueError("canonical source changed during validation")
    return {"identity":identity,"revision":a["plan_revision"],"body_hash":digest(body),"attestation_hash":digest(raw),"production_commit":sha,"production_state":response["production_state"],"assets":a["assets"],"files":files}


def _revision_conflict(prior, bundle, directory):
    """The fixed reason for a same-or-lower revision that the receiver cannot take."""
    if int(prior["plan_revision"]) != bundle["revision"] or prior["content_sha256"] != bundle["body_hash"]:
        return "REVISION_CONFLICT"
    try:
        published = json.loads((directory / "public-plan-attestation.json").read_bytes()).get("assets", [])
        published = sorted((a["path"], a["sha256"]) for a in published)
        current = sorted((a["path"], a["sha256"]) for a in bundle["assets"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return "REVISION_CONFLICT"
    if published != current:
        return "REVISION_CONFLICT media changed at the same plan revision"
    return "REVISION_CONFLICT attestation changed at the same plan revision"


def _unbound_preflight(result):
    return (result.get('status') in {'BLOCKED_CONFIGURATION', 'BLOCKED_POLICY'}
            and result.get('source_refs') == [] and result.get('changed_paths') == []
            and result.get('public_ids') == [])


def project_attested(source, *, internal_output_root, public_projection_root, state_root, batch=False, fail_after=None, child_python=None):
    from tools import public_projection as p
    expected="PASSED" if batch else "PLAN_READY"
    run_id,target=p._automatic_report_resolution(source,internal_output_root=internal_output_root,public_projection_root=public_projection_root,state_root=state_root,expected_status=expected)
    internal=internal_output_root.resolve()
    before=p._automatic_safe_target_fingerprint(target)
    refs=[]; public_ids=[]; changed=[]; planned=[]; findings=[]; after=before
    request_locator=None
    status="BLOCKED_POLICY"
    try:
        if target is None:
            status="BLOCKED_CONFIGURATION";raise ValueError("configure public_projection_root")
        layout=p._load_target_document(target,"public-project.yaml","layout")
        if not isinstance(layout,dict) or p.validate_layout(layout) or layout.get("canonical_plan",{}).get("projection_contract")!="canonical-plan-projection/v2" or layout.get("collections")!={"plans":"plans","works":"works"}:
            raise ValueError("explicit plans/works receiver layout required")
        items=source.get("projects") if batch else [source]
        if not isinstance(items,list) or not items or (batch and (any(i.get("status")!="PASSED" for i in items) or source.get("completed_count")!=len(items))):
            raise ValueError("all batch projects must be PASSED")
        bundles=[]
        for item in items:
            # Identical bytes already projected at the same revision are kept
            # as they are, with their public attestation (a no-op, not a revision).
            bundle = _published_bundle(item, internal, target)
            if bundle is None:
                bundle = (_owner_bundle(item, internal, child_python)
                          if child_python is not None else _owner_bundle(item, internal))
            slug=item.get("project_slug",item.get("project_id"));title=item.get("project_title",item.get("title",slug))
            if isinstance(title,str):title=p.plan_record_title(title,bundle["files"]["plan.md"])
            if not isinstance(slug,str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",slug) or not isinstance(title,str) or not title.strip():raise ValueError("explicit safe project slug/title required")
            if p.scan_public_projection({"title":title,"body":bundle["files"]["plan.md"].decode()},"canonical-plan"):
                raise ValueError("public content policy blocked canonical bytes")
            media_policy=layout["media_policy"]
            if any(len(data)>media_policy["max_file_bytes"] for data in bundle["files"].values()) or any(Path(name).suffix not in media_policy["allowed_extensions"] for name in bundle["files"] if name.startswith("media/")):
                raise ValueError("receiver media limits rejected source")
            bundles.append((bundle,slug,title))
        bundles.sort(key=lambda row:row[0]["identity"])
        if len({b[0]["identity"] for b in bundles})!=len(bundles):raise ValueError("duplicate source identity in batch")
        refs=[{"record_kind":"plan","source_sha256":b["body_hash"],"source_identity":b["identity"],"plan_revision":b["revision"],"attestation_sha256":b["attestation_hash"],"production_commit":b["production_commit"],"production_repository":"masa-san-jp/agentic-art-production","source_run_id":run_id,"body_transform":"none","assets":b['assets']} for b,_,_ in bundles]
        request={"contract_version":"canonical-plan-projection/v2","mode":"AUTOMATIC_PLAN","canonical_artifact":"production-plan.md","body_transform":"none","refs":refs}
        previous_result=state_root/run_id/"public-projection-result.json"
        if previous_result.exists():
            previous=json.loads(previous_result.read_text())
            if previous.get("request_sha256")!=p.sha256_hex(request) and not _unbound_preflight(previous):
                status="BLOCKED_CONFLICT";raise ValueError("run ID already belongs to a different projection request")
        request_locator=f'public-projection/{run_id}/canonical-request.json'
        p._write_create_only(internal,request_locator,(json.dumps(request,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode())
        index_path=target/"plans/index.yaml";index=yaml.safe_load(index_path.read_text())
        if not isinstance(index,dict) or set(index)!={"version","records","retired_ids"} or not isinstance(index["records"],list):raise ValueError("receiver index contract required")
        old=index["records"]; by_identity={r.get("source_identity"):r for r in old}
        if len(by_identity)!=len(old) or any(not r.get("source_identity") or r.get("projection_contract")!="canonical-plan-projection/v2" for r in old):raise ValueError("legacy target needs authorized migration")
        for record in old:
            if not re.fullmatch(r'P[0-9]{4}',str(record.get('id',''))) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',str(record.get('slug',''))) or record.get('path')!=f"plans/{record['id']}-{record['slug']}":
                raise ValueError('existing record path does not match stable ID')
            p._target_locator(target,record['path'],'existing.record')
        reservations=list(index["retired_ids"])
        migration=target/"plans/migration.yaml"
        if migration.exists():reservations.extend(r["id"] for r in yaml.safe_load(migration.read_text()).get("records",[]))
        used=[r["id"] for r in old]+reservations
        if set(r['id'] for r in old)&set(reservations) or len({r['id'] for r in old})!=len(old):
            raise ValueError('reserved or duplicate public ID is in use')
        if any(not re.fullmatch(r"P[0-9]{4}",identifier) for identifier in used):raise ValueError("invalid reserved P ID")
        next_id=max([int(i[1:]) for i in used],default=0)+1
        writes={};updates={};removals={};expected_paths=set();new_records=list(old)
        for b,slug,title in bundles:
            prior=by_identity.get(b["identity"])
            if prior:
                public_id=prior["id"];slug=prior["slug"]
                old_directory=target/prior["path"]
                if digest((old_directory/"plan.md").read_bytes())!=prior["content_sha256"] or digest((old_directory/"public-plan-attestation.json").read_bytes())!=prior["attestation_sha256"]:
                    status="BLOCKED_CONFLICT";raise ValueError("existing canonical record was modified")
                if int(prior["plan_revision"])>b["revision"] or (int(prior["plan_revision"])==b["revision"] and (prior["content_sha256"]!=b["body_hash"] or prior["attestation_sha256"]!=b["attestation_hash"])):
                    status="BLOCKED_CONFLICT"
                    # Production raises plan_revision only through a superseding handoff
                    # (new_production.py --accept-revision); a re-render under the same
                    # handoff keeps it.  Name the changed part so the stop is not misread.
                    raise ValueError(_revision_conflict(prior, b, old_directory))
            else:
                if next_id>9999:raise ValueError("public ID range exhausted")
                public_id=f"P{next_id:04d}";next_id+=1
            directory=f"plans/{public_id}-{slug}";public_ids.append(public_id)
            metadata={"id":public_id,"slug":slug,"title":title,"source_key":"plan:"+b["identity"],"source_identity":b["identity"],"plan_revision":str(b["revision"]),
                "production_repository":"masa-san-jp/agentic-art-production","production_commit":b["production_commit"],"source_run_id":run_id,
                "content_sha256":b["body_hash"],"attestation_sha256":b["attestation_hash"],"projection_contract":"canonical-plan-projection/v2","projection_mode":"AUTOMATIC_PLAN","body_transform":"none",
                "plan_state":"canonical","production_state":b["production_state"],"visibility":"public","external_effects_authorized":"false","status":"ready-for-publication","rights_status":"cleared"}
            metadata.update(contract_version='canonical-plan-projection/v2',mode='AUTOMATIC_PLAN',canonical_artifact='production-plan.md',assets=json.dumps(b['assets'],sort_keys=True,separators=(',',':')))
            readme_bytes = p._generated_readme(metadata, "plan", canonical_body=b["files"]["plan.md"])
            try:
                readme_text = readme_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("generated Project introduction must be UTF-8") from exc
            if p.scan_public_projection(readme_text, f"plans/{public_id}-{slug}/README.md"):
                raise ValueError("generated Project introduction failed public content policy")
            metadata.update(
                introduction_contract=p.PROJECT_PLAN_INTRODUCTION_CONTRACT,
                introduction_revision=str(b["revision"]),
                introduction_sha256=p._sha256_bytes(readme_bytes),
            )
            entry=dict(metadata,path=directory)
            if prior and int(prior["plan_revision"])==b["revision"]:
                metadata={k:v for k,v in prior.items() if k!="path"};entry=prior
            files=dict(b["files"],**{"metadata.yaml":p._request_yaml_bytes(metadata),"README.md":readme_bytes})
            if prior:
                from tools.plan_view import PlanViewError, generated_view_files, strip_block, supplemental_files
                same=int(prior["plan_revision"])==b["revision"]
                current_readme=p._target_regular(target/directory/"README.md","record.README")[0]
                if same:
                    # The same revision keeps its README and the README-only supplemental media
                    # (tools/plan_view.py) bound to it, so a resumed run stays ALREADY_PROJECTED.
                    files["README.md"]=current_readme
                    try:
                        supplemental=supplemental_files(target,directory,public_id)
                    except PlanViewError:
                        status="BLOCKED_CONFLICT";raise ValueError("supplemental media manifest was modified")
                else:
                    # A new revision gets the README generated for it.  It may drop only what this
                    # harness made: its own generated view, and a README equal to the generated one
                    # for the prior revision.  Curated media or text needs an explicit migration.
                    try:
                        supplemental=generated_view_files(target,directory,public_id)
                    except PlanViewError as exc:
                        status="BLOCKED_CONFLICT"
                        raise ValueError("curated supplemental media requires migration" if str(exc)=="CURATED_SUPPLEMENTAL_MEDIA"
                                         else "supplemental media manifest was modified")
                    prior_body=p._target_regular(target/directory/"plan.md","record.plan")[0]
                    generated=p._generated_readme({k:v for k,v in prior.items() if k!="path"},"plan",canonical_body=prior_body)
                    try:
                        current_text=current_readme.decode("utf-8")
                    except UnicodeDecodeError:
                        current_text=""
                    if (strip_block(current_text) if supplemental else current_text).encode("utf-8")!=generated:
                        status="BLOCKED_CONFLICT";raise ValueError("curated README requires migration")
                existing={x.relative_to(target).as_posix() for x in (target/directory).rglob('*') if x.is_file()}
                allowed={directory+'/'+name for name in files}
                if same:
                    allowed|=set(supplemental);expected_paths.update(supplemental)
                else:
                    for relative,raw in supplemental.items():
                        if relative not in allowed:removals[relative]=raw;expected_paths.add(relative)
                obsolete=existing-allowed-set(removals)
                if obsolete:
                    old_attestation=json.loads((target/directory/'public-plan-attestation.json').read_bytes())
                    old_assets={directory+'/'+a['path'][8:]:a['sha256'] for a in old_attestation.get('assets',[]) if a['path'].startswith('03_plan/media/') and '..' not in Path(a['path']).parts}
                    if int(prior['plan_revision'])>=b['revision'] or obsolete-set(old_assets):
                        raise ValueError("unowned record files require explicit migration")
                    for relative in obsolete:
                        raw=p._target_regular(p._target_locator(target,relative,relative)[1],relative)[0]
                        if 'sha256:'+digest(raw)!=old_assets[relative]:
                            status='BLOCKED_CONFLICT';raise ValueError('obsolete asset changed')
                        removals[relative]=raw;expected_paths.add(relative)
                new_records=[r for r in new_records if r["id"]!=public_id]
            for name,data in files.items():
                relative=directory+'/'+name;path=target/relative;expected_paths.add(relative)
                if path.exists():
                    if not prior:raise ValueError("unindexed target record collision")
                    current,_=p._target_regular(path,relative)
                    if current!=data:
                        if int(prior["plan_revision"])==b["revision"]:status="BLOCKED_CONFLICT";raise ValueError("existing revision bytes conflict")
                        updates[relative]=(current,data)
                else:writes[relative]=data
            new_records.append(entry)
        index["records"]=sorted(new_records,key=lambda r:r["id"])
        index_bytes=p._index_bytes(index)
        if index_path.read_bytes()!=index_bytes:updates["plans/index.yaml"]=(index_path.read_bytes(),index_bytes)
        readme=target/"plans/README.md";text=readme.read_text()
        rendered=p._replace_marker_block(text,layout,p._catalog_text(index,"plans"),"plans.README").encode()
        if readme.read_bytes()!=rendered:updates["plans/README.md"]=(readme.read_bytes(),rendered)
        root_update=p._root_catalog_update(target,layout,index)
        if root_update and root_update[0]!=root_update[1]:updates["README.md"]=root_update
        expected_paths.update({"plans/index.yaml","plans/README.md"})
        if root_update is not None:expected_paths.add("README.md")
        # The Project's own catalog generator (run.py runs it after a projection) rewrites this
        # derived file; a resumed run must not read that as an unrelated change.
        if (target/"plans/lineage-index.json").is_file():expected_paths.add("plans/lineage-index.json")
        dirty=p._git_target_status_paths(target)
        if dirty is None or set(dirty)-(expected_paths|set(updates)):
            status="BLOCKED_CONFLICT";raise ValueError("unrelated dirty target paths")
        planned=sorted(set(writes)|set(updates)|set(removals))
        if planned:
            outcome=p._apply_projection_transaction(target,before=before,planned_files=writes,target_updates=updates,target_removals=removals,fail_after=fail_after)
            status=outcome["outcome"];changed=outcome["changed_paths"];after=outcome["after"];findings=outcome["findings"]
        else:status="ALREADY_PROJECTED"
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError, p.PreparationError) as exc:
        code="TARGET_CONFLICT" if status=="BLOCKED_CONFLICT" else "CONFIGURATION_MISSING" if status=="BLOCKED_CONFIGURATION" else "FORBIDDEN_CONTENT"
        # Keep the fixed reason so an agent can tell a missing attestation from
        # a receiver index defect; see _failure_reason for what is never kept.
        findings=[p._projection_finding(code,"canonical-plan-projection/v2","Require qualified owner attestation, stable identity/revision and reviewed receiver layout; preserve existing data. reason: "+_failure_reason(exc))]
        changed=[];after=p._automatic_safe_target_fingerprint(target)
    result=p._automatic_terminal_result(projection_id=run_id,generated_at=p._automatic_safe_generated_at(source),request_hash=p.sha256_hex({"contract_version":"canonical-plan-projection/v2","mode":"AUTOMATIC_PLAN","canonical_artifact":"production-plan.md","body_transform":"none","refs":refs}),source_refs=refs,status=status,findings=findings,before=before,after=after,public_ids=public_ids,planned_paths=planned,changed_paths=changed)
    previous_path=state_root/run_id/'public-projection-result.json'
    # A different request may not overwrite successful receipts. Return the
    # conflict for the caller's run report, retaining the original evidence.
    if previous_path.exists() and json.loads(previous_path.read_text()).get('request_sha256')!=result['request_sha256']:
        previous_bytes = previous_path.read_bytes()
        if not _unbound_preflight(json.loads(previous_bytes)):
            return p._automatic_summary(result,request_locator=request_locator)
        # A failed preflight bound no source and wrote no catalog bytes. Retain
        # that evidence before binding the first validated request on resume.
        archive = previous_path.with_name('unbound-preflight-' + digest(previous_bytes) + '.json')
        if archive.is_symlink() or (archive.exists() and archive.read_bytes() != previous_bytes):
            raise ValueError('PREFLIGHT_EVIDENCE_CONFLICT')
        if not archive.exists():
            with archive.open('xb') as stream: stream.write(previous_bytes)
        if previous_path.is_symlink() or previous_path.read_bytes() != previous_bytes:
            raise ValueError('PREFLIGHT_EVIDENCE_CHANGED')
        previous_path.unlink()
    p._write_projection_result(state_root,run_id,result,allow_transition=True)
    return p._automatic_summary(result,request_locator=request_locator)
