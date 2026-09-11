"""Delivery goals and completion reporting shared by production entrypoints."""
from __future__ import annotations

from pathlib import Path

from tools.validate import _schema_errors, load_json

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_SCHEMA = ROOT / 'schemas/delivery-contract.schema.json'
COMPLETION_SCHEMA = ROOT / 'schemas/delivery-completion.schema.json'
TARGETS = {'internal', 'project-local', 'project-committed'}
CONTRACT_VERSION = 'delivery-contract/v1'


def validate_contract(value):
    """Return closed-schema and profile-independent contract findings."""
    if not isinstance(value, dict):
        return ['delivery contract must be an object']
    return _schema_errors(value, load_json(CONTRACT_SCHEMA), 'delivery-contract/v1')


def validate_completion(value):
    if not isinstance(value, dict):
        return ['delivery completion must be an object']
    return _schema_errors(value, load_json(COMPLETION_SCHEMA), 'delivery-completion/v1')


def _profile_allows(value, profile):
    if value['target'].startswith('project-') and (
            profile.get('delivery_mode') != 'public-catalog'
            or not profile.get('permissions', {}).get('public_projection')):
        raise ValueError('DELIVERY_PROFILE_MISMATCH')
    if value['target'] == 'internal' and profile.get('delivery_mode') != 'internal':
        raise ValueError('DELIVERY_PROFILE_MISMATCH')
    return value


def normal_contract(profile, *, requested_target=None):
    """Resolve a new normal run without relying on an optional flag.

    A public profile defaults to the local receiver.  The older committed
    catalog meaning is selected only by ``resolve_contract(...,
    legacy_context=True)`` for a saved legacy context.
    """
    if not isinstance(profile, dict):
        raise ValueError('DELIVERY_PROFILE_REQUIRED')
    target = requested_target or ('internal' if profile.get('delivery_mode') == 'internal' else 'project-local')
    value = {'contract_version': CONTRACT_VERSION, 'target': target}
    errors = validate_contract(value)
    if errors:
        raise ValueError('DELIVERY_CONTRACT_INVALID')
    return _profile_allows(value, profile)


def resolve_contract(value, profile, *, legacy_context=False):
    if value is None:
        if legacy_context:
            return {'contract_version': CONTRACT_VERSION, 'target': 'internal' if profile['delivery_mode'] == 'internal' else 'project-committed'}
        return normal_contract(profile)
    if validate_contract(value):
        raise ValueError('DELIVERY_CONTRACT_INVALID')
    return _profile_allows(dict(value), profile)


def normal_contract_for_destinations(destination_resolution, *, project_root_selected=False):
    """Resolve the normal non-cycle entry's contract from its selected root."""
    if project_root_selected:
        value = {'contract_version': CONTRACT_VERSION, 'target': 'project-local'}
        if validate_contract(value):
            raise ValueError('DELIVERY_CONTRACT_INVALID')
        return value
    destinations = destination_resolution.get('destinations', {}) if isinstance(destination_resolution, dict) else {}
    public = destinations.get('public_projection_root') if isinstance(destinations, dict) else None
    # v1 destination profiles are legacy-compatible and retain their committed
    # catalog meaning until a caller explicitly opts into project-local v2.
    target = 'project-committed' if isinstance(public, dict) else 'internal'
    value = {'contract_version': CONTRACT_VERSION, 'target': target}
    if validate_contract(value):
        raise ValueError('DELIVERY_CONTRACT_INVALID')
    return value


def completion(state, contract):
    """Summarize freshly owner-verified results, never a worker's success flag."""
    missing=[]
    if isinstance(state.get('projects'), list):
        if (state.get('status') != 'PASSED'
                or state.get('completed_count') != state.get('requested_count')
                or state.get('failed_count') != 0
                or any(not isinstance(project, dict) or project.get('status') != 'PASSED'
                       for project in state.get('projects', []))):
            missing.append('PRODUCTION_PLAN')
    else:
        plan=state.get('plan')
        if state.get('plan_status')!='PLAN_READY' or not isinstance(plan,dict) or not plan.get('artifacts') or plan.get('owner_verification',{}).get('plan_status')!='PLAN_READY':
            missing.append('PRODUCTION_PLAN')
    if state.get('knowledge_status')!='COMMITTED':
        missing.append('KNOWLEDGE_COMMIT')
    if contract['target']!='internal':
        local=state.get('local_delivery_receipt',{})
        if contract['target']=='project-local':
            if state.get('projection_status')!='PROJECTED' or local.get('contract_version')!='local-plan-delivery-receipt/v1' or local.get('status')!='VERIFIED' or not local.get('records'):
                missing.append('PROJECT_LOCAL_DELIVERY')
        elif state.get('projection_status')!='PROJECTED' or not state.get('catalog_receipt',{}).get('knowledge_commit'):
            missing.append('PROJECT_COMMITTED_DELIVERY')
    result = {'contract_version':'delivery-completion/v1','target':contract['target'],
              'status':'COMPLETED' if not missing else 'INCOMPLETE','missing':missing}
    if validate_completion(result):
        raise ValueError('DELIVERY_COMPLETION_INVALID')
    return result
