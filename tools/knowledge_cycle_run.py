#!/usr/bin/env python3
"""Resume an external agent's plan and native-owner knowledge completion."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import subprocess

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.instance_profiles import OWNERS, bootstrap, load_profile
from tools.knowledge_cycle import canonical, registry
from tools.native_knowledge import NativeKnowledgeError, external_path, initializer, invoke
from tools.plan_completion import PlanCompletionError, checked_code, verify_plan
from tools.validate import _schema_errors, load_json

POLICY = json.loads((ROOT / 'config/knowledge-cycle-runtime.json').read_text())


def hashed(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read(path):
    path = external_path(path)
    return json.loads(path.read_bytes())


def save(path, value):
    path = external_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('STATE_SYMLINK')
    temporary = path.with_name(path.name + '.pending')
    if temporary.is_symlink():
        raise ValueError('STATE_SYMLINK')
    temporary.write_bytes(canonical(value))
    temporary.replace(path)


def validate_receipt(receipt, owner, binding, run_id, operation_id):
    import subprocess
    if _schema_errors(receipt, load_json(ROOT / 'schemas/knowledge-write-receipt.schema.json')):
        raise ValueError('OWNER_RECEIPT_CONTRACT')
    if (receipt['owner'], receipt['collection'], receipt['run_id'], receipt['operation_id']) != (owner, binding['collection'], run_id, operation_id):
        raise ValueError('OWNER_RECEIPT_BINDING')
    if receipt['status'] not in {'COMMITTED', 'ALREADY_APPLIED', 'NO_CHANGE', 'INDEX_PENDING'}:
        raise ValueError('OWNER_WRITE_NOT_ACCEPTED')
    target, parent = receipt['target_commit'], receipt['target_parent']
    if any(not re.fullmatch('[0-9a-f]{40}', str(x)) for x in (target, parent)):
        raise ValueError('OWNER_RECEIPT_COMMIT_MISSING')
    git = ['git', '--git-dir', str(Path(binding['store_root']) / 'objects.git')]
    for old, new in [(parent, target), (target, 'refs/heads/knowledge')]:
        subprocess.run([*git, 'merge-base', '--is-ancestor', old, new], check=True, capture_output=True)
    return receipt


def _bindings(context, profile, local, state_root):
    result = {}
    allowed = {'python', 'profile_root', 'subject', 'catalog_root', 'catalog_repository', 'catalog_snapshot', 'catalog_collection'}
    for owner in OWNERS:
        entry = profile['repositories'][owner]
        options = context.get('owner_options', {}).get(owner, {})
        if set(options) - allowed:
            raise ValueError('NATIVE_OWNER_OPTION_FORBIDDEN')
        binding = {**options, 'creator': profile['creator_id'], 'collection': entry['knowledge_store_id'],
            'code_commit': entry['code_commit'],
            'code_root': str(state_root / 'instances' / profile['instance_id'] / 'runs' / context['run_id'] / 'code' / owner),
            'store_root': local['stores'][entry['knowledge_store_id']]['path']}
        if owner == 'agentic-art-project' and 'catalog_collection' in options:
            collection = options['catalog_collection']
            grant = local['collections'].get(collection, {})
            if collection not in entry['source_collections'] or profile['creator_id'] not in grant.get('readers', []):
                raise ValueError('CATALOG_COLLECTION_NOT_AUTHORIZED')
        elif owner == 'agentic-art-project' and any(k.startswith('catalog_') for k in options):
            raise ValueError('CATALOG_COLLECTION_REQUIRED')
        result[owner] = binding
    return result


def _query(owner, binding, inputs, snapshot, context):
    result = invoke(owner, binding, 'query', inputs, snapshot=snapshot,
        run_id=context['run_id'], operation_id=context['run_id'] + '-' + owner, clock=context['clock'])
    # Curated domain output stays in that owner's external cache, never parent Git/state.
    path = Path(binding['store_root']) / 'cycle-queries' / (context['run_id'] + '-' + snapshot + '-' + hashed([inputs, context['clock']])[:12] + '.json')
    if path.exists() and read(path) != result:
        raise ValueError('PINNED_QUERY_CHANGED')
    save(path, result)
    return {'owner': owner, 'snapshot': snapshot, 'query_hash': hashed(inputs),
            'result_hash': hashed(result), 'result_ref': str(path), 'evaluated_at': context['clock']}


def advance(context, state_root):
    """One bounded checkpoint. The external agent consumes returned next_action."""
    required = {'contract_version', 'run_id', 'instance_profile', 'local_config', 'clock',
                'production_project_root', 'query_inputs', 'write_inputs'}
    optional = {'owner_options', 'delivery_contract', 'project_root', 'project_id'}
    if not isinstance(context, dict) or set(context) - (required | optional) or not required <= set(context) or context['contract_version'] != 'knowledge-cycle-context/v1':
        raise ValueError('CYCLE_CONTEXT_CONTRACT')
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,100}', context['run_id']):
        raise ValueError('RUN_ID_INVALID')
    if set(context['query_inputs']) != set(OWNERS) or set(context['write_inputs']) != set(OWNERS) - {'agentic-art-project'}:
        raise ValueError('ALL_OWNER_DECISIONS_REQUIRED')
    if datetime.fromisoformat(context['clock'].replace('Z', '+00:00')).tzinfo is None:
        raise ValueError('EXPLICIT_CLOCK_REQUIRED')
    state_root = external_path(state_root)
    profile, local = load_profile(external_path(context['instance_profile'])), read(context['local_config'])
    from tools.delivery_completion import resolve_contract
    delivery_contract = resolve_contract(context.get('delivery_contract'), profile)
    project_resolution = None
    if context.get('project_root') is not None:
        from tools.repo_local_destinations import resolve_project_root
        if not delivery_contract['target'].startswith('project-'):
            raise ValueError('PROJECT_ROOT_REQUIRES_PROJECT_DELIVERY')
        project_resolution = resolve_project_root(
            context['project_root'], run_id=context['run_id'], project_id=context.get('project_id'))
        derived_state = external_path(project_resolution['destinations']['state_root']['path'])
        if state_root != derived_state:
            raise ValueError('STATE_ROOT_DESTINATION_CONFLICT')
        configured = local.get('output_destinations', {})
        if configured.get('contract_version') == 'output-destinations/v2' and configured.get('project_root') != project_resolution['project_root']:
            raise ValueError('PROJECT_ROOT_DESTINATION_CONFLICT')
        # The v2 resolver is authoritative for all repo-local paths.  Keep the
        # external knowledge-store config, but replace only its destination
        # adapter so bootstrap cannot fall back to v1 or an arbitrary public
        # directory.
        local = dict(local)
        local['output_destinations'] = {
            'contract_version': 'output-destinations/v2',
            'mode': 'repo-local-project',
            'project_root': project_resolution['project_root'],
            'destinations': {key: value['relative'] for key, value in project_resolution['destinations'].items()},
        }
    elif delivery_contract['target'] == 'project-local':
        raise ValueError('PROJECT_ROOT_REQUIRED')
    if project_resolution is not None and delivery_contract['target'] == 'project-committed':
        raise ValueError('REPO_LOCAL_PROJECT_COMMITTED_REQUIRES_EXPLICIT_COMMIT')
    checked_code(ROOT, profile['repositories']['agentic-art-orchestration']['code_commit'])
    binding = _bindings(context, profile, local, state_root)
    factories = {o: f for o in OWNERS if (f := initializer(o, binding[o], profile['instance_id'], context['clock']))}
    resolution = bootstrap(profile, local, state_root, run_id=context['run_id'], owner_initializers=factories)
    project = external_path(context['production_project_root'])
    destination_evidence = resolution['destination_resolution']
    internal = external_path(destination_evidence['destinations']['internal_output_root']['path'])
    if internal not in project.parents:
        raise ValueError('PLAN_OUTSIDE_INTERNAL_DESTINATION')
    run_root = state_root / 'knowledge-cycles' / context['run_id']
    run_root.mkdir(parents=True, exist_ok=True)
    lock_path = run_root / 'cycle.lock'
    if lock_path.is_symlink():
        raise ValueError('LEASE_SYMLINK')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('CYCLE_LEASE_HELD') from exc
        state_path = run_root / 'cycle.json'
        identity = hashed({'context': context, 'profile': profile, 'local': local, 'resolution': resolution})
        state = read(state_path) if state_path.exists() else {
            'contract_version': 'knowledge-cycle-run/v1', 'run_id': context['run_id'], 'input_fingerprint': identity,
            'creator_id': profile['creator_id'], 'origin_instance_id': profile['instance_id'],
            'plan_status': 'RESEARCH_PENDING', 'knowledge_status': 'PENDING', 'projection_status': 'SKIPPED',
            'run_status': 'RUNNING', 'queries': {}, 'owners': {}, 'attempts': {}, 'no_progress': 0,
            'plan': None, 'stop_reason': None, 'next_action': None}
        if state['input_fingerprint'] != identity:
            raise ValueError('RUN_PROFILE_OR_SNAPSHOT_CHANGED')
        state['delivery_contract'] = delivery_contract
        old_progress = hashed([state['queries'], state['owners'], state['plan']])
        context_path = run_root / 'context.json'
        if context_path.exists() and read(context_path) != context:
            raise ValueError('SAVED_CONTEXT_CHANGED')
        save(context_path, context)
        state['resume_command'] = [sys.executable, str(ROOT / 'tools/run.py'), '--cycle-context', str(context_path), '--state-root', str(state_root)]
        state['heartbeat'] = datetime.now(timezone.utc).isoformat()
        state['lease'] = {'status': 'held', 'seconds': POLICY['lease_seconds'], 'expires_at': (datetime.now(timezone.utc) + timedelta(seconds=POLICY['lease_seconds'])).isoformat()}
        save(state_path, state)
        try:
            _advance(context, profile, resolution, binding, project, state, run_root)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            code = str(exc) if re.fullmatch('[A-Z][A-Z0-9_]{1,100}', str(exc)) else type(exc).__name__
            state.update(run_status='INCOMPLETE', stop_reason=code,
                next_action={'actor': 'agent', 'do': 'Inspect the named boundary failure, preserve completed artifacts and receipts, and repair only the incomplete stage.'})
        finally:
            progress = hashed([state['queries'], state['owners'], state['plan']])
            awaiting_human = isinstance(state.get('next_action'), dict) and state['next_action'].get('actor') == 'human'
            if not awaiting_human:
                state['no_progress'] = state['no_progress'] + 1 if progress == old_progress and state['run_status'] != 'COMPLETED' else 0
            from tools.delivery_completion import completion
            state['delivery_completion'] = completion(state, delivery_contract)
            state['completion_status'] = state['delivery_completion']['status']
            if state['run_status'] == 'COMPLETED' and state['completion_status'] != 'COMPLETED':
                state['run_status'] = 'INCOMPLETE'
            if not awaiting_human and state['no_progress'] >= POLICY['max_no_progress']:
                state.update(run_status='INCOMPLETE', stop_reason='NO_PROGRESS_LIMIT', next_action={'actor': 'agent', 'do': 'Inspect the recorded failed stage before starting a new bounded execution.'})
            state['lease']['status'] = 'released'
            save(state_path, state)
        return state


def _advance(context, profile, resolution, bindings, project, state, run_root):
    run_id = context['run_id']
    started = time.monotonic()
    def heartbeat():
        if time.monotonic() - started >= POLICY['max_checkpoint_seconds']:
            raise ValueError('CHECKPOINT_TIME_LIMIT')
        state['heartbeat'] = datetime.now(timezone.utc).isoformat()
        if 'lease' in state:
            state['lease']['expires_at'] = (datetime.now(timezone.utc) + timedelta(seconds=POLICY['lease_seconds'])).isoformat()
        save(run_root / 'cycle.json', state)
    for owner in OWNERS:
        heartbeat()
        b = bindings[owner]
        path = external_path(context['query_inputs'][owner])
        if not path.is_file():
            state.update(next_action={'actor': 'agent', 'stage': 'query', 'owner': owner, 'input': str(path), 'do': 'Prepare native query arguments from this run scope; keep unknowns explicit.'})
            return
        inputs = read(path)
        snapshot = b.get('catalog_snapshot', resolution['knowledge_refs'][owner]['commit']) if owner == 'agentic-art-project' else resolution['knowledge_refs'][owner]['commit']
        query = _query(owner, b, inputs, snapshot, context)
        if owner in state['queries'] and state['queries'][owner] != query:
            raise ValueError('COMPLETED_QUERY_CHANGED')
        state['queries'][owner] = query
    b = bindings['agentic-art-production']
    try:
        verified = verify_plan(code_root=b['code_root'], code_commit=b['code_commit'], project_root=project,
            python=b.get('python'), expected=state['plan']['artifacts'] if state['plan'] else None,
            research_commit=resolution['code_refs']['agentic-art-research']['commit'])
    except (PlanCompletionError, OSError) as exc:
        state.update(plan_status='PLAN_BUILDING', run_status='INCOMPLETE', stop_reason=type(exc).__name__,
            next_action={'actor': 'agent', 'stage': 'plan', 'project_root': str(project),
                'query_refs': [q['result_ref'] for q in state['queries'].values()],
                'do': 'Consume the pinned knowledge queries, complete native Research/handoff, and build an actionable Production plan. Resume this same context after the owner validator passes.'})
        return
    state.update(plan=verified, plan_status='PLAN_READY', stop_reason=None)
    save(run_root / 'cycle.json', state)  # Preserve the verified plan before any owner write.
    for owner in OWNERS:
        heartbeat()
        if owner == 'agentic-art-project':
            continue
        b = bindings[owner]
        path = external_path(context['write_inputs'][owner])
        if not path.is_file():
            state.update(knowledge_status='PARTIAL' if state['owners'] else 'PENDING', run_status='INCOMPLETE',
                next_action={'actor': 'agent', 'stage': 'knowledge', 'owner': owner, 'input': str(path),
                    'do': 'Prepare a native write job or an explicit no-new-evidence decision. Research and Production require curated persistence.'})
            return
        job = read(path)
        if set(job) != {'action', 'inputs', 'reason'} or job['action'] not in {'write', 'no-new-evidence'} or not isinstance(job['reason'], str) or not job['reason'].strip():
            raise ValueError('OWNER_JOB_CONTRACT')
        input_hashes = {}
        for key, value in job['inputs'].items():
            from tools.native_knowledge import PATH_INPUTS
            if key in PATH_INPUTS and isinstance(value, str):
                source = external_path(value)
                if source.is_file():
                    input_hashes[key] = hashlib.sha256(source.read_bytes()).hexdigest()
        job_hash = hashed([job, input_hashes])
        saved = state['owners'].get(owner)
        op = run_id + '-' + owner
        if saved and saved['job_hash'] != job_hash:
            raise ValueError('COMPLETED_OWNER_INPUT_CHANGED')
        if saved:
            if saved.get('receipt'):
                validate_receipt(saved['receipt'], owner, b, run_id, op)
                # A saved success JSON is insufficient: the native idempotency
                # path verifies the original payload/operation and Git commit.
                replay = invoke(owner, b, 'write', job['inputs'],
                    snapshot=resolution['knowledge_refs'][owner]['commit'], run_id=run_id,
                    operation_id=op, clock=saved['write_clock'])
                if replay.get('status') == 'NO_NEW_EVIDENCE':
                    replay.update(status='NO_CHANGE', reason='NO_NEW_EVIDENCE')
                validate_receipt(replay, owner, b, run_id, op)
                if any(replay[k] != saved['receipt'][k] for k in ('target_parent', 'target_commit', 'accepted_ids', 'rejected_ids')):
                    raise ValueError('COMPLETED_NATIVE_RECEIPT_CHANGED')
                query = _query(owner, b, read(context['query_inputs'][owner]), replay['target_commit'], {**context, 'clock': saved['write_clock']})
                if query != saved['query']:
                    raise ValueError('COMPLETED_NATIVE_QUERY_CHANGED')
            continue
        if job['action'] == 'no-new-evidence':
            if owner in {'agentic-art-research', 'agentic-art-production'} or job['inputs']:
                raise ValueError('CURATED_RESEARCH_AND_PLAN_PERSISTENCE_REQUIRED')
            state['owners'][owner] = {'job_hash': job_hash, 'knowledge_status': 'NO_NEW_EVIDENCE',
                'query_ref': state['queries'][owner]['result_ref'], 'reason_hash': hashed(job['reason'])}
            save(run_root / 'cycle.json', state)
            continue
        if not all(profile['permissions'][k] for k in ('local_knowledge_write', 'local_git_commit')):
            raise ValueError('LOCAL_PERSISTENCE_PERMISSION_REQUIRED')
        if state['attempts'].get(owner, 0) >= POLICY['max_owner_attempts']:
            state.update(knowledge_status='PARTIAL', run_status='INCOMPLETE', stop_reason='OWNER_RETRY_LIMIT', next_action={'actor': 'agent', 'owner': owner, 'do': 'Inspect the native failure; preserve successful owner receipts.'})
            return
        operations = state.setdefault('operations', {})
        operation = operations.get(owner)
        if operation is None or operation['job_hash'] != job_hash:
            if operation is not None and (run_root / (owner + '-receipt.json')).exists():
                raise ValueError('COMMITTED_OPERATION_INPUT_CHANGED')
            operation = {'job_hash': job_hash, 'clock': datetime.now(timezone.utc).isoformat()}
            operations[owner] = operation
        write_context = {**context, 'clock': operation['clock']}
        save(run_root / 'cycle.json', state)
        try:
            receipt = invoke(owner, b, 'write', job['inputs'], snapshot=resolution['knowledge_refs'][owner]['commit'],
                run_id=run_id, operation_id=op, clock=operation['clock'])
            if receipt.get('status') == 'NO_NEW_EVIDENCE':
                receipt.update(status='NO_CHANGE', reason='NO_NEW_EVIDENCE')
            validate_receipt(receipt, owner, b, run_id, op)
            save(run_root / (owner + '-receipt.json'), receipt)
            if owner in {'art-history-notes', 'agentic-art-research', 'agentic-art-orchestration'}:
                inputs = {'receipt': str(run_root / (owner + '-receipt.json'))} if owner == 'agentic-art-orchestration' else {}
                index = invoke(owner, b, 'index', inputs, snapshot=receipt['target_commit'], run_id=run_id, operation_id=op, clock=operation['clock'])
                receipt.update(index_commit=index['index_commit'], index_hash=index['index_hash'])
            query = _query(owner, b, read(context['query_inputs'][owner]), receipt['target_commit'], write_context)
            if owner == 'viewer-response-notes':
                receipt.update(index_commit=receipt['target_commit'], index_hash=query['result_hash'])
            if receipt['status'] == 'INDEX_PENDING' or not receipt['index_commit'] or not receipt['index_hash']:
                raise NativeKnowledgeError('NATIVE_INDEX_PENDING')
            validate_receipt(receipt, owner, b, run_id, op)
            state['owners'][owner] = {'job_hash': job_hash, 'write_clock': operation['clock'], 'knowledge_status': 'COMMITTED' if receipt['accepted_ids'] else 'NO_NEW_EVIDENCE', 'receipt': receipt, 'query': query}
            save(run_root / (owner + '-receipt.json'), receipt)
        except (NativeKnowledgeError, OSError, ValueError, subprocess.SubprocessError) as exc:
            state['attempts'][owner] = state['attempts'].get(owner, 0) + 1
            state.update(knowledge_status='PARTIAL', run_status='INCOMPLETE', stop_reason=type(exc).__name__,
                next_action={'actor': 'agent', 'stage': 'knowledge', 'owner': owner, 'do': 'Inspect native input/receipt, repair this owner only, and resume the identical context. Successful plans and receipts are retained.'})
            save(run_root / 'cycle.json', state)
            return
        save(run_root / 'cycle.json', state)
    state['knowledge_status'] = 'COMMITTED'
    if profile['delivery_mode'] == 'internal':
        state.update(projection_status='SKIPPED', run_status='COMPLETED', stop_reason=None, next_action=None)
    else:
        _public_completion(context, profile, resolution, bindings, project, state, run_root)


def _public_completion(context, profile, resolution, bindings, project, state, run_root):
    from tools.canonical_plan_projection import source_fields
    from tools.public_projection import build_automatic_plan_authority, project_plan_automatic
    run_id = context['run_id']
    # A canonical PLAN_READY record uses the closed automatic-plan authority.
    # It must not enter the human publication-review lane: that lane is for
    # work/manual requests and external effects. Production still performs its
    # own renderer, content, asset and provenance checks before writing the
    # mechanical attestation. A failed mechanical check is an agent repair
    # action, never an inferred request for consent.
    binding = bindings['agentic-art-production']
    code = checked_code(binding['code_root'], binding['code_commit'])
    command = [binding.get('python', sys.executable), str(code/'tools/public_plan_attestation.py'),
        '--project-root', str(project), '--automatic-plan', '--producer-commit', binding['code_commit'], '--generated-at', context['clock']]
    result = subprocess.run(command, cwd=code, capture_output=True, text=True, timeout=120)
    if result.returncode:
        try:
            finding = json.loads(result.stdout)
        except ValueError:
            finding = {'status': 'REJECTED', 'reason': result.stderr.strip() or 'automatic attestation failed'}
        packet = run_root / 'automatic-plan-attestation.json'
        save(packet, finding)
        state.update(run_status='INCOMPLETE', projection_status='BLOCKED', stop_reason='PRODUCTION_AUTOMATIC_ATTESTATION_FAILED',
            next_action={'actor':'agent', 'stage':'attestation', 'receipt':str(packet), 'command':command,
                         'do':'Repair the reported Production plan, renderer, asset, or provenance finding and resume the identical run.'})
        return
    destinations = resolution['destination_resolution']
    internal = Path(destinations['destinations']['internal_output_root']['path'])
    public = Path(destinations['destinations']['public_projection_root']['path'])
    state_root = run_root.parent.parent
    source = {'run_id': run_id, 'status': 'PLAN_READY', 'generated_at': context['clock'],
        'project_slug': project.name, 'project_title': project.name,
        'production_repository': 'agentic-art-production',
        'production_source_commit': bindings['agentic-art-production']['code_commit'],
        'production_plan_sha256': state['plan']['artifacts']['03_plan/production-plan.md'],
        'destination_resolution': destinations,
        **source_fields(project / '03_plan/production-plan.md', bindings['agentic-art-production']['code_root'])}
    source['automatic_plan_authority'] = build_automatic_plan_authority(producer='tools/run.py',
        source_status='PLAN_READY', source_id=run_id, source_sha256=source['production_plan_sha256'],
        destination_resolution=destinations)
    projected = state.get('projection_receipt')
    if not isinstance(projected, dict) or projected.get('status') not in {'APPLIED', 'ALREADY_PROJECTED'}:
        projected = project_plan_automatic(source, internal_output_root=internal, public_projection_root=public,
            state_root=state_root, projection_id=run_id)
    state['projection_receipt'] = projected
    state.update(projection_status='BLOCKED', run_status='INCOMPLETE', stop_reason='PUBLIC_PROJECTION_PENDING',
        next_action={'actor': 'agent', 'stage': 'projection', 'receipt': projected['result_locator'],
            'do': 'Resolve the native canonical projection findings. Preserve explicit rights, consent and human gates.'})
    if projected['status'] not in {'APPLIED', 'ALREADY_PROJECTED'}:
        if projected['status'] == 'FAILED':
            state['projection_status'] = 'FAILED'
        return
    if context.get('delivery_contract', {}).get('target') == 'project-local':
        binding = bindings['agentic-art-project']
        code = checked_code(binding['code_root'], binding['code_commit'])
        python = binding.get('python', sys.executable)
        for identifier in projected['public_ids']:
            subprocess.run([python, str(code/'tools/catalog_lineage.py'), 'annotate', '--root', str(public),
                '--record-id', identifier, '--instance-profile', context['instance_profile'], '--mode', 'new', '--initialize-new', '--apply'],
                cwd=code, check=True, capture_output=True, text=True, timeout=120)
        subprocess.run([python, str(code/'tools/catalog_sync.py'), '--root', str(public), '--write'], cwd=code, check=True, capture_output=True, timeout=120)
        expected = [{'record_id':identifier, 'content_sha256':source['production_plan_sha256'],
            'creator_id':profile['creator_id'], 'origin_instance_id':profile['instance_id'], 'source_identity':source['source_identity']}
            for identifier in projected['public_ids']]
        expectation = run_root/'expected-delivery.json'
        save(expectation, expected)
        result = subprocess.run([python, str(code/'tools/local_delivery.py'), '--root', str(public), '--expected', str(expectation)],
            cwd=code, capture_output=True, text=True, timeout=120)
        receipt = json.loads(result.stdout)
        save(run_root/'local-delivery.json', receipt)
        if result.returncode or receipt.get('status') != 'VERIFIED' or receipt.get('contract_version') != 'local-plan-delivery-receipt/v1':
            state.update(stop_reason='PROJECT_LOCAL_DELIVERY_INVALID', next_action={'actor':'agent','stage':'projection','receipt':str(run_root/'local-delivery.json')})
            return
        checked_code(code, binding['code_commit'])
        state.update(projection_status='PROJECTED', run_status='COMPLETED', stop_reason=None, next_action=None, local_delivery_receipt=receipt)
        return
    # The Project owner verifies committed receiver bytes, attribution and lineage.
    # Do not turn a parent projection success JSON into catalog acceptance.
    snapshot = subprocess.check_output(['git', '-C', str(public), 'rev-parse', 'HEAD'], text=True).strip()
    b = {**bindings['agentic-art-project'], 'catalog_root': str(public)}
    catalog = invoke('agentic-art-project', b, 'query', {}, snapshot=snapshot,
        run_id=run_id, operation_id=run_id+'-projection', clock=context['clock'])
    records = {r['record_id']: r for r in catalog.get('records', [])}
    ids = projected['public_ids']
    if not ids or any(i not in records or records[i]['content_sha256'] != source['production_plan_sha256']
        or records[i]['creator_id'] != profile['creator_id'] or records[i]['origin_instance_id'] != profile['instance_id']
        or records[i]['source_identity'] != source.get('source_identity') for i in ids):
        state.update(stop_reason='PROJECT_LINEAGE_NOT_VERIFIED', next_action={'actor': 'agent', 'stage': 'projection',
            'public_ids': ids, 'creator_id': profile['creator_id'], 'origin_instance_id': profile['instance_id'],
            'do': 'Use native Project lineage/validation for these new records, preserve inherited authors, and complete any permitted local catalog commit before resuming. Remote publication and human gates remain separate.'})
        return
    state.update(projection_status='PROJECTED', run_status='COMPLETED', stop_reason=None, next_action=None,
        catalog_receipt={'knowledge_commit': snapshot, 'result_hash': hashed(catalog), 'record_ids': ids})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True, type=Path)
    parser.add_argument('--state-root', required=True, type=Path)
    args = parser.parse_args()
    result = advance(read(args.context), args.state_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['run_status'] == 'COMPLETED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
