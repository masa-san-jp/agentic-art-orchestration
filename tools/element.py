#!/usr/bin/env python3
"""Emit one request, check one answer and persist a resumable element sequence."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.element_checks import check_value, valid_url
from tools.element_contracts import DEFAULT_REGISTRY, load_sequence, require_message, validate_sequence


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n'


def build_inputs(bindings: dict, answers: dict, context: dict) -> dict:
    """Resolve only declared bindings. Never send the whole context to a model."""
    def resolve(binding):
        if 'literal' in binding:
            return deepcopy(binding['literal'])
        if 'answer' in binding:
            return deepcopy(answers[binding['answer']])
        if 'context' in binding:
            return deepcopy(context[binding['context']])
        ref = binding['search_result']
        return deepcopy(answers[ref['element_id']][ref['index']][ref['field']])
    return {key: resolve(binding) for key, binding in bindings.items()}


def _has_private_elements(sequence: object) -> bool:
    return (isinstance(sequence, dict) and isinstance(sequence.get('elements'), list)
            and any(isinstance(item, dict) and item.get('private') is True
                    for item in sequence['elements']))


class Engine:
    def __init__(self, run_id: str, state_root: Path, *, project_root: Path | None = None):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', run_id):
            raise ValueError('Unsafe run ID')
        root = state_root.expanduser().resolve()
        if not state_root.expanduser().is_absolute() or root == Path(root.anchor):
            raise ValueError('Use a dedicated absolute Git-external state root')
        if project_root is not None:
            from tools.repo_local_destinations import resolve_project_root
            resolution = resolve_project_root(project_root, run_id=run_id)
            permitted = Path(resolution['destinations']['state_root']['path']).resolve()
            if root != permitted:
                raise ValueError('Element state differs from the validated Project destination')
        elif root == ROOT or ROOT in root.parents or any((p / '.git').exists() for p in (root, *root.parents)):
            raise ValueError('Element state must stay outside Git checkouts')
        self.directory = root / run_id
        # Reject run-local symlinks rather than follow them into another run.
        if self.directory.is_symlink() or self.directory.resolve() != self.directory:
            raise ValueError('Unsafe run state directory')
        self.path = self.directory / 'element-state.json'
        self.run_id = run_id

    @contextmanager
    def _locked(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError('Unsafe state file')
        lock = self.directory / 'element.lock'
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def _read(self) -> dict:
        if self.path.is_symlink():
            raise ValueError('Unsafe state file')
        state = json.loads(self.path.read_text(encoding='utf-8'))
        if state['run_id'] != self.run_id or state['contract_version'] != 'element-state/v1':
            raise ValueError('State identity mismatch')
        return state

    def _save(self, state: dict) -> None:
        # Pending request and accepted answer are one atomic checkpoint; a
        # crash cannot advance the cursor without the next request being saved.
        with tempfile.NamedTemporaryFile(dir=self.directory, mode='w', encoding='utf-8', delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(canonical(state))
                handle.flush()
                os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
        fd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _request(self, state: dict) -> None:
        if state['index'] == len(state['sequence']['elements']) and state['sequence'].get('driver') == 'phase-a':
            from tools.theme_elements import advance
            advance(state)
            if state['status'] == 'BLOCKED':
                return
        if state['index'] == len(state['sequence']['elements']):
            state.update(status='COMPLETED', pending=None)
            return
        item = state['sequence']['elements'][state['index']]
        if item.get('private'):
            raise ValueError('Private requests must stay in the owner relay')
        request = {'contract_version': f"{item['kind']}-request/v1", 'run_id': self.run_id,
                   'element_id': item['element_id'], 'attempt': state['attempt'],
                   'previous_failure': state['previous_failure']}
        if item['kind'] == 'search':
            query = build_inputs({'query': item['query']}, state['answers'], state['context'])['query']
            request.update(query=query, limit=item['limit'])
        else:
            inputs = build_inputs(item['inputs'], state['answers'], state['context'])
            if len(canonical(inputs).encode('utf-8')) > 4096:
                raise ValueError('Element inputs exceed the 4096-byte request budget')
            request.update(instruction=item['instruction'], inputs=inputs,
                           answer_format=item['answer_format'], checks=item['checks'])
        require_message(request, f"{item['kind']}-request")
        state.update(status='WAITING', pending=canonical(request))

    def next(self, *, sequence: dict | None = None, context: dict | None = None,
             registry: Path = DEFAULT_REGISTRY) -> dict:
        if context is not None and not isinstance(context, dict):
            raise ValueError('Context must be an object')
        if sequence is not None:
            if _has_private_elements(sequence):
                raise ValueError('Private requests must be relayed to the owner without parent persistence')
            sequence = deepcopy(sequence)
            if isinstance(sequence, dict):
                sequence.setdefault('max_attempts', 5)
        with self._locked():
            if self.path.exists():
                state = self._read()
                if sequence is not None and state['sequence'] != sequence:
                    raise ValueError('Sequence differs from the saved run')
                if context is not None and state['context'] != context:
                    raise ValueError('Context differs from the saved run')
            else:
                sequence = deepcopy(sequence if sequence is not None else load_sequence(registry))
                if _has_private_elements(sequence):
                    raise ValueError('Private requests must stay in the owner relay')
                errors = validate_sequence(sequence)
                if errors:
                    raise ValueError('; '.join(errors))
                commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                                        text=True, check=True).stdout.strip()
                state = {'contract_version': 'element-state/v1', 'run_id': self.run_id,
                         'sequence': sequence, 'context': deepcopy(context or {}),
                         'source_repository': 'agentic-art-orchestration', 'source_commit': commit,
                         'index': 0, 'attempt': 1, 'previous_failure': None, 'answers': {},
                         'ledger': {}, 'history': [], 'pending': None, 'status': 'WAITING'}
                self._request(state)
                self._save(state)
            return self._report(state)

    def status(self) -> dict:
        with self._locked():
            return self._report(self._read())

    def request_bytes(self) -> bytes | None:
        with self._locked():
            value = self._read()['pending']
            return value.encode('utf-8') if value is not None else None

    def _report(self, state: dict) -> dict:
        pending = json.loads(state['pending']) if state['pending'] else None
        return {'run_id': self.run_id, 'status': state['status'], 'accepted_count': len(state['answers']),
                'answers': deepcopy(state['answers']), 'blocked': deepcopy(state.get('blocked')),
                'next_action': {'kind': 'element', 'request': pending} if pending else None}

    def answer(self, answer: object) -> dict:
        with self._locked():
            state = self._read()
            # A sender may lose stdout after the checkpoint was saved. Replay
            # its exact recorded answer without checking or advancing it again.
            if isinstance(answer, dict) and answer.get('run_id') == self.run_id:
                answer_sha256 = hashlib.sha256(canonical(answer).encode()).hexdigest()
                if any(saved['element_id'] == answer.get('element_id')
                       and saved['attempt'] == answer.get('attempt')
                       and saved['answer_sha256'] == answer_sha256
                       for saved in state['history']):
                    return self._report(state)
            if state['status'] != 'WAITING':
                raise ValueError('Run is not waiting for an answer')
            request = json.loads(state['pending'])
            kind = request['contract_version'].split('-')[0]
            # Malformed/wrong/stale envelopes never consume an attempt.
            require_message(answer, f'{kind}-answer')
            if any(answer[key] != request[key] for key in ('run_id', 'element_id', 'attempt')):
                raise ValueError('Answer does not match the pending request identity and attempt')
            failures = []
            if kind == 'search':
                results = answer['results']
                if not results:
                    failures.append({'check': 'non_empty', 'reason': 'Return at least one retrieved result.'})
                if len(results) > request['limit']:
                    failures.append({'check': 'search_limit', 'reason': 'Return at most the requested number of results.'})
                urls = [r['url'] for r in results]
                if len(set(urls)) != len(urls):
                    failures.append({'check': 'unique_urls', 'reason': 'Return each URL once.'})
                for result in results:
                    if not valid_url(result['url']):
                        failures.append({'check': 'url_shape', 'reason': 'Return a valid HTTP(S) URL without credentials.'})
                    if not result['title'].strip() or not result['body'].strip():
                        failures.append({'check': 'non_empty', 'reason': 'Return a non-empty title and retrieved body.'})
                    if result['url'] in state['ledger'] and state['ledger'][result['url']]['body'] != result['body']:
                        failures.append({'check': 'source_conflict', 'reason': 'This URL already has a different pinned body.'})
                value = results
            else:
                value = answer['value']
                fmt = request['answer_format']
                text = value.get('reason') if isinstance(value, dict) else value
                if fmt['type'] == 'boolean_with_reason':
                    shape_ok = isinstance(value, dict)
                else:
                    shape_ok = isinstance(value, str)
                if not shape_ok:
                    failures.append({'check': 'answer_format', 'reason': 'Use the requested value type.'})
                if isinstance(text, str):
                    if fmt['type'] == 'choice' and value not in fmt['choices']:
                        failures.append({'check': 'choice', 'reason': 'Return exactly one supplied choice.'})
                    if len(text) > fmt.get('max_chars', 2048) or len(text) < fmt.get('min_chars', 1):
                        failures.append({'check': 'character_count', 'reason': 'Respect the requested character limits.'})
                    if fmt['type'] == 'url' and not valid_url(value):
                        failures.append({'check': 'url_shape', 'reason': 'Return a valid HTTP(S) URL without credentials.'})
                failures.extend(check_value(value, request['checks'], inputs=request['inputs'],
                                            ledger=state['ledger'], previous_answers={**state['answers'], **{
                                                f'prior-operation-{i}': word for i, word in enumerate(
                                                    state['context'].get('phase_a', {}).get('prior_operations', [])
                                                    if request['element_id'] == 'A3.operation' else [])}}))
            state['history'].append({'element_id': request['element_id'], 'attempt': request['attempt'],
                                     'answer_sha256': hashlib.sha256(canonical(answer).encode()).hexdigest(),
                                     'failures': failures})
            if failures:
                state['previous_failure'] = failures
                if state['attempt'] >= state['sequence']['max_attempts']:
                    state.update(status='BLOCKED', pending=None,
                                 blocked={'element_id': request['element_id'], 'attempt': state['attempt'],
                                          'last_failure': failures})
                else:
                    state['attempt'] += 1
                    self._request(state)
            else:
                state['answers'][request['element_id']] = value
                if kind == 'search':
                    for result in value:
                        state['ledger'].setdefault(result['url'], {
                            **result, 'body_sha256': hashlib.sha256(result['body'].encode('utf-8')).hexdigest(),
                            'element_id': request['element_id'], 'attempt': request['attempt'],
                            'source_repository': state['source_repository'], 'source_commit': state['source_commit']})
                state.update(index=state['index'] + 1, attempt=1, previous_failure=None)
                try:
                    self._request(state)
                except (KeyError, IndexError, ValueError):
                    # Preserve accepted work even if a later binding cannot be
                    # built. This is a configuration block, not a bad answer.
                    element_id = state['sequence']['elements'][state['index']]['element_id']
                    failure = [{'check': 'input_build', 'reason': 'Repair the next element input binding or request budget.'}]
                    state.update(status='BLOCKED', pending=None,
                                 blocked={'element_id': element_id, 'attempt': 1, 'last_failure': failure})
            self._save(state)
            return self._report(state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('next', 'answer', 'status'))
    parser.add_argument('--run-id', required=True)
    destinations = parser.add_mutually_exclusive_group(required=True)
    destinations.add_argument('--state-root', type=Path)
    destinations.add_argument('--project-root', type=Path, help='explicit Project checkout; validate its repo-local state destination')
    parser.add_argument('--registry', type=Path, default=DEFAULT_REGISTRY,
                        help='declarative sequence used only when initializing a run')
    args = parser.parse_args(argv)
    try:
        state_root = args.state_root
        if args.project_root is not None:
            from tools.repo_local_destinations import resolve_project_root
            resolution = resolve_project_root(args.project_root, run_id=args.run_id)
            state_root = Path(resolution['destinations']['state_root']['path'])
        engine = Engine(args.run_id, state_root, project_root=args.project_root)
        if args.command == 'answer':
            report = engine.answer(json.load(sys.stdin))
        elif args.command == 'next':
            report = engine.next(registry=args.registry)
        else:
            report = engine.status()
        sys.stdout.write(canonical(report))
        return 2 if report['status'] == 'BLOCKED' else 0
    except (OSError, ValueError, KeyError, IndexError) as exc:
        print(canonical({'status': 'ERROR', 'detail': str(exc)}), end='', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
