"""Production-owned attestation boundary and exact-byte projection/v2 transaction."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import subprocess
import yaml


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


def _owner_bundle(item, internal):
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
    command=[str(code/".venv/bin/python"),"tools/public_plan_attestation.py","--project-root",str(project),"--check"]
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


def _unbound_preflight(result):
    return (result.get('status') in {'BLOCKED_CONFIGURATION', 'BLOCKED_POLICY'}
            and result.get('source_refs') == [] and result.get('changed_paths') == []
            and result.get('public_ids') == [])


def project_attested(source, *, internal_output_root, public_projection_root, state_root, batch=False, fail_after=None):
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
            bundle=_owner_bundle(item,internal)
            slug=item.get("project_slug",item.get("project_id"));title=item.get("project_title",item.get("title",slug))
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
                    status="BLOCKED_CONFLICT";raise ValueError("REVISION_CONFLICT")
            else:
                if next_id>9999:raise ValueError("public ID range exhausted")
                public_id=f"P{next_id:04d}";next_id+=1
            directory=f"plans/{public_id}-{slug}";public_ids.append(public_id)
            metadata={"id":public_id,"slug":slug,"title":title,"source_key":"plan:"+b["identity"],"source_identity":b["identity"],"plan_revision":str(b["revision"]),
                "production_repository":"masa-san-jp/agentic-art-production","production_commit":b["production_commit"],"source_run_id":run_id,
                "content_sha256":b["body_hash"],"attestation_sha256":b["attestation_hash"],"projection_contract":"canonical-plan-projection/v2","projection_mode":"AUTOMATIC_PLAN","body_transform":"none",
                "plan_state":"canonical","production_state":b["production_state"],"visibility":"public","external_effects_authorized":"false","status":"ready-for-publication","rights_status":"cleared"}
            metadata.update(contract_version='canonical-plan-projection/v2',mode='AUTOMATIC_PLAN',canonical_artifact='production-plan.md',assets=json.dumps(b['assets'],sort_keys=True,separators=(',',':')))
            entry=dict(metadata,path=directory)
            if prior and int(prior["plan_revision"])==b["revision"]:
                metadata={k:v for k,v in prior.items() if k!="path"};entry=prior
            files=dict(b["files"],**{"metadata.yaml":p._request_yaml_bytes(metadata),"README.md":p._generated_readme(metadata,"plan")})
            if prior:
                files["README.md"]=p._target_regular(target/directory/"README.md","record.README")[0]
                existing={x.relative_to(target).as_posix() for x in (target/directory).rglob('*') if x.is_file()}
                allowed={directory+'/'+name for name in files}
                obsolete=existing-allowed
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
        findings=[p._projection_finding(code,"canonical-plan-projection/v2","Require qualified owner attestation, stable identity/revision and reviewed receiver layout; preserve existing data. "+("REVISION_CONFLICT" if str(exc)=="REVISION_CONFLICT" else ""))]
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
