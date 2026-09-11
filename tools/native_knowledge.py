"""Provider-neutral calls to pinned native knowledge CLIs; no domain schema copies."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys

from tools.plan_completion import checked_code
from tools.path_safety import external_path as _safe_external_path

BARE_OWNERS = {'self-model-notes', 'marketing-trends-notes', 'agentic-art-production'}
POLICY = json.loads((Path(__file__).resolve().parents[1] / "config/knowledge-cycle-runtime.json").read_text())
TOOLS = {
    'self-model-notes': 'tools/creative_feedback.py',
    'art-history-notes': 'tools/research_knowledge_intake.py',
    'marketing-trends-notes': 'tools/research_intake.py',
    'agentic-art-research': 'tools/research_memory.py',
    'agentic-art-production': 'tools/production_memory.py',
    'viewer-response-notes': 'tools/viewer_memory.py',
    'agentic-art-project': 'tools/catalog_lineage.py',
    'agentic-art-orchestration': 'tools/knowledge_cycle.py',
}
# Arguments are native-owner inputs, never an arbitrary executable/shell command.
INPUTS = {
    'self-model-notes': {'record', 'query'},
    'art-history-notes': {'candidate', 'source-snapshots', 'query', 'scope'},
    'marketing-trends-notes': {'record', 'geo', 'channel'},
    'agentic-art-research': {'candidate', 'query', 'conditions'},
    'agentic-art-production': {'project', 'request', 'project-id', 'environment'},
    'viewer-response-notes': {'candidate', 'scope'},
    'agentic-art-project': set(),
    'agentic-art-orchestration': {'record', 'payload-root', 'query', 'access-scope', 'decisions', 'receipt'},
}
PATH_INPUTS = {'record', 'candidate', 'source-snapshots', 'conditions', 'project', 'request', 'environment', 'payload-root', 'decisions', 'receipt'}


class NativeKnowledgeError(ValueError):
    pass


def external_path(value):
    try:
        return _safe_external_path(value)
    except ValueError as exc:
        raise NativeKnowledgeError(str(exc)) from exc


def _execute(binding, args, *, accepted_failure_statuses=frozenset()):
    """Run an owner command, retaining only explicitly safe read statuses.

    Project catalog export is read-only. An existing catalog may contain an
    intentionally preserved unknown-attribution record; that makes the export
    result BLOCKED, but does not authorize changing or consuming that record.
    All callers must opt into retaining such a status, so writes and other
    owner failures remain fail-closed.
    """
    code = checked_code(binding['code_root'], binding['code_commit'])
    process = subprocess.run([binding.get('python', sys.executable), *map(str, args)], cwd=code,
                             capture_output=True, text=True, timeout=POLICY["step_timeout_seconds"])
    checked_code(binding['code_root'], binding['code_commit'])
    try:
        result = json.loads(process.stdout)
    except ValueError as exc:
        raise NativeKnowledgeError('NATIVE_RESPONSE_INVALID') from exc
    if not isinstance(result, dict):
        raise NativeKnowledgeError('NATIVE_RESPONSE_INVALID')
    if process.returncode:
        if result.get('status') in accepted_failure_statuses:
            return result
        # Do not persist arbitrary owner stderr, private source text or raw data.
        raise NativeKnowledgeError('NATIVE_' + str(result.get('status', 'REJECTED')))
    return result


def initializer(owner, binding, instance, clock):
    """Factory used by instance bootstrap after materializing qualified code."""
    if owner not in BARE_OWNERS:
        return None
    def create(path, code):
        b = {**binding, 'code_root': str(code)}
        common = ['--creator', b['creator'], '--collection', b['collection']]
        if owner == 'agentic-art-production':
            args = [TOOLS[owner], '--store', path, *common, 'init', '--instance', instance]
        else:
            args = [TOOLS[owner], 'init', '--store-root', path, *common, '--instance', instance]
            if owner == 'self-model-notes':
                args += ['--profile-root', external_path(b['profile_root']), '--subject', b['subject']]
            else:
                args += ['--now', clock]
        _execute(b, args)
    return create


def command(owner, binding, action, inputs, *, snapshot, run_id, operation_id, clock):
    """Build only existing owner read/write operations with bound identity/pins."""
    if owner not in TOOLS or action not in {'write', 'query', 'index'}:
        raise NativeKnowledgeError('OWNER_OPERATION_UNSUPPORTED')
    if not isinstance(inputs, dict) or set(inputs) - INPUTS[owner]:
        raise NativeKnowledgeError('NATIVE_INPUT_ARGUMENT_FORBIDDEN')
    root = external_path(binding['store_root'])
    store = root / 'objects.git' if owner in BARE_OWNERS else root
    extra = []
    for key, value in inputs.items():
        values = value if key == 'channel' and isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str) or not item or item.startswith('--'):
                raise NativeKnowledgeError('NATIVE_INPUT_ARGUMENT_INVALID')
            if key in PATH_INPUTS or (key == 'scope' and owner == 'viewer-response-notes'):
                external_path(item)
            extra += ['--' + key, item]
    common = ['--creator', binding['creator'], '--collection', binding['collection']]
    pinned = ['--code-commit', binding['code_commit'], '--knowledge-commit', snapshot]
    operation = ['--operation-id', operation_id, '--run-id', run_id]
    if owner == 'agentic-art-production':
        args = [TOOLS[owner], '--store', store, *common]
        if action == 'write':
            return [*args, 'ingest', '--parent', snapshot, '--operation', operation_id, '--run-id', run_id, *extra]
        if action == 'index':
            raise NativeKnowledgeError('PRODUCTION_INDEX_RETRY_USES_IDEMPOTENT_INGEST')
        return [*args, 'query', '--snapshot', snapshot, '--at', clock, *extra]
    if owner == 'agentic-art-project':
        if action != 'query':
            raise NativeKnowledgeError('PROJECT_IS_READ_ONLY')
        return [TOOLS[owner], 'export', '--root', external_path(binding['catalog_root']),
                '--repository', binding['catalog_repository'], '--snapshot', snapshot]
    name = {'write': 'commit', 'query': 'retrieve', 'index': 'index'}[action]
    if owner == 'viewer-response-notes':
        name = {'write': 'append', 'query': 'query'}.get(action)
        if name is None:
            raise NativeKnowledgeError('VIEWER_QUERY_IS_REGENERATED_INDEX')
    if owner == 'agentic-art-orchestration':
        return [TOOLS[owner], name, '--store', store, '--owner', owner, *common, *pinned,
                *(operation if action == 'write' else []), *(['--at', clock] if action == 'query' else []), *extra]
    args = [TOOLS[owner], name, '--store-root', store, *common]
    if owner == 'self-model-notes':
        args += ['--profile-root', external_path(binding['profile_root']), '--subject', binding['subject']]
        args += ['--expected-parent', snapshot, '--operation-id', operation_id] if action == 'write' else ['--snapshot', snapshot]
    elif owner == 'marketing-trends-notes':
        args += ['--now', clock]
        args += ['--expected-parent', snapshot, *operation] if action == 'write' else ['--snapshot', snapshot]
    else:
        args += pinned
        if action == 'write':
            args += operation
        elif action == 'query':
            args += ['--at', clock]
    return [*args, *extra]


def invoke(owner, binding, action, inputs, **context):
    if owner == 'agentic-art-orchestration' and action == 'query':
        # The parent native retriever deliberately requires an index. Rebuild
        # that disposable view from the selected immutable Git snapshot first.
        snapshot = context['snapshot']
        receipt = {'contract_version': 'knowledge-write-receipt/v1',
            'operation_id': context['operation_id'] + '-index', 'run_id': context['run_id'],
            'owner': owner, 'collection': binding['collection'], 'target_parent': snapshot,
            'target_commit': snapshot, 'accepted_ids': [], 'rejected_ids': [],
            'schema_version': 'artifact-record/v1', 'policy_version': 'knowledge-cycle/v1',
            'index_commit': None, 'index_hash': None, 'status': 'NO_CHANGE',
            'reason': 'Read-only snapshot index request; no knowledge write'}
        path = external_path(binding['store_root']) / 'cycle-index-inputs' / (snapshot + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        external_path(path)
        path.write_text(json.dumps(receipt))
        _execute(binding, command(owner, binding, 'index', {'receipt': str(path)}, **context))
    accepted_failure_statuses = {'BLOCKED'} if owner == 'agentic-art-project' and action == 'query' else set()
    return _execute(binding, command(owner, binding, action, inputs, **context),
                    accepted_failure_statuses=accepted_failure_statuses)
