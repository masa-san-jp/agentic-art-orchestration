"""Delivery goals and completion reporting shared by production entrypoints."""
from __future__ import annotations

TARGETS={'internal','project-local','project-committed'}


def resolve_contract(value, profile):
    if value is None:
        return {'contract_version':'delivery-contract/v1','target':'internal' if profile['delivery_mode']=='internal' else 'project-committed'}
    if not isinstance(value,dict) or set(value)!={'contract_version','target'} or value['contract_version']!='delivery-contract/v1' or value['target'] not in TARGETS:
        raise ValueError('DELIVERY_CONTRACT_INVALID')
    if value['target'].startswith('project-') and (profile['delivery_mode']!='public-catalog' or not profile['permissions'].get('public_projection')):
        raise ValueError('DELIVERY_PROFILE_MISMATCH')
    if value['target']=='internal' and profile['delivery_mode']!='internal':
        raise ValueError('DELIVERY_PROFILE_MISMATCH')
    return dict(value)


def completion(state, contract):
    """Summarize freshly owner-verified results, never a worker's success flag."""
    missing=[]
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
    return {'contract_version':'delivery-completion/v1','target':contract['target'],
            'status':'COMPLETED' if not missing else 'INCOMPLETE','missing':missing}
