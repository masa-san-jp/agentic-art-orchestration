#!/usr/bin/env python3
"""Answer exactly one request using a deterministic fake or a configured local command."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
from jsonschema import Draft202012Validator
from tools.element import canonical
from tools.element_contracts import require_message


def request_kind(request: dict) -> str:
    if not isinstance(request, dict):
        raise ValueError('Request must be a JSON object')
    version = request.get('contract_version')
    if not isinstance(version, str):
        raise ValueError('Unsupported request contract')
    kind = version.removesuffix('-request/v1')
    if kind not in {'element', 'search'}:
        raise ValueError('Unsupported request contract')
    require_message(request, f'{kind}-request')
    return kind


class FakeAnswerer:
    """A fixture maps each ID to values by attempt. No heuristic inference."""
    def __init__(self, values: dict | None = None):
        self.values = deepcopy(values if values is not None else {
            'demo.operation': ['先送り'],
            'demo.question': ['先送りは時間をどう変えるか？'],
            'demo.category': ['時間'],
        })

    def answer(self, request: dict) -> dict:
        kind = request_kind(request)
        values = self.values[request['element_id']]
        value = deepcopy(values[min(request['attempt'] - 1, len(values) - 1)])
        return {'contract_version': f'{kind}-answer/v1',
                **{key: request[key] for key in ('run_id', 'element_id', 'attempt')},
                **({'answerer_kind': 'fake'} if kind == 'element' else {}),
                'results' if kind == 'search' else 'value': value}


class LocalAnswerer:
    def __init__(self, config: dict):
        contract = {
            'type': 'object', 'additionalProperties': False,
            'required': ['contract_version', 'command', 'timeout_seconds'],
            'properties': {
                'contract_version': {'const': 'element-answerer/v1'},
                'command': {'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'minLength': 1}},
                'timeout_seconds': {'type': 'integer', 'minimum': 1},
            },
        }
        if not Draft202012Validator(contract).is_valid(config):
            raise ValueError('Invalid element-answerer/v1 configuration')
        self.config = deepcopy(config)

    def answer(self, request: dict) -> dict:
        kind = request_kind(request)
        try:
            result = subprocess.run(self.config['command'], input=canonical(request),
                                    capture_output=True, text=True, encoding='utf-8',
                                    timeout=self.config['timeout_seconds'], check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError('Local answerer did not return an answer') from exc
        if result.returncode:
            raise ValueError(f'Local answerer exited with code {result.returncode}')
        try:
            answer = json.loads(result.stdout)  # rejects multiple JSON documents
        except ValueError as exc:
            raise ValueError('Local answerer must return one JSON answer on stdout') from exc
        require_message(answer, f'{kind}-answer')
        if any(answer[key] != request[key] for key in ('run_id', 'element_id', 'attempt')):
            raise ValueError('Local answer does not match the request')
        return answer  # acceptance checks remain the Engine's responsibility


class StableChoiceAnswerer:
    def __init__(self, backend, answerer_kind):
        self.backend = backend
        self.answerer_kind = answerer_kind

    def answer(self, request):
        from tools.choice_answerer import orders, presentation, original_value
        observations = []
        for order in orders(request):
            changed = presentation(request, order)
            start = time.monotonic()
            reply = self.backend.answer(changed)
            elapsed = time.monotonic() - start
            value = original_value(request, order, reply['value'])
            observations.append({'order': order, 'value': reply['value'],
                                 'request_sha256': hashlib.sha256(canonical(changed).encode()).hexdigest(),
                                 'elapsed_seconds': elapsed,
                                 'cost_usd': reply.get('inference_usage', {}).get('cost_usd')})
            if len(observations) == 1:
                first = value
        # An unstable pair is still submitted: the Engine consumes the attempt
        # and applies its existing five-attempt limit, rather than an unbounded worker retry.
        return {'contract_version': 'element-answer/v1',
                **{key: request[key] for key in ('run_id', 'element_id', 'attempt')},
                'value': first, 'answerer_kind': self.answerer_kind,
                'choice_observations': observations}


class RoutingAnswerer:
    """Versioned format dispatch; model commands remain external workers."""
    def __init__(self, config):
        route = {'type': 'object', 'additionalProperties': False,
                 'required': ['command', 'timeout_seconds', 'answerer_kind'],
                 'properties': {
                     'command': {'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'minLength': 1}},
                     'timeout_seconds': {'type': 'integer', 'minimum': 1},
                     'answerer_kind': {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9._-]{0,39}$'}}}
        contract = {'type': 'object', 'additionalProperties': False,
                    'required': ['contract_version', 'default', 'formats'],
                    'properties': {'contract_version': {'const': 'element-answerer/v2'},
                                   'default': route,
                                   'formats': {'type': 'object', 'additionalProperties': False,
                                               'properties': {kind: route for kind in
                                                              ['choice', 'text', 'url', 'boolean_with_reason', 'search']}}}}
        if not Draft202012Validator(contract).is_valid(config):
            raise ValueError('Invalid element-answerer/v2 configuration')
        if config['default']['answerer_kind'].startswith('judge-'):
            raise ValueError('A judgement-only backend cannot be the default text answerer')
        if any(key != 'choice' and value['answerer_kind'].startswith('judge-')
               for key, value in config['formats'].items()):
            raise ValueError('Judgement backends only support choice answers')
        self.config = deepcopy(config)

    def answer(self, request):
        kind = request_kind(request)
        fmt = 'search' if kind == 'search' else request['answer_format']['type']
        route = self.config['formats'].get(fmt, self.config['default'])
        backend = LocalAnswerer({'contract_version': 'element-answerer/v1',
                                'command': route['command'], 'timeout_seconds': route['timeout_seconds']})
        if fmt == 'choice' and route['answerer_kind'].startswith('judge-'):
            return StableChoiceAnswerer(backend, route['answerer_kind']).answer(request)
        answer = backend.answer(request)
        if kind == 'element':
            answer['answerer_kind'] = route['answerer_kind']
        return answer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--fake', action='store_true', help='synthetic demo only')
    mode.add_argument('--config', type=Path, help='local command argv and timeout, never a shell expression')
    args = parser.parse_args(argv)
    try:
        if args.fake:
            answerer = FakeAnswerer()
        else:
            config = yaml.safe_load(args.config.read_text(encoding='utf-8'))
            if not isinstance(config, dict):
                raise ValueError('Answerer configuration must be an object')
            answerer = RoutingAnswerer(config) if config.get('contract_version') == 'element-answerer/v2' else LocalAnswerer(config)
        sys.stdout.write(canonical(answerer.answer(json.load(sys.stdin))))
        return 0
    except (OSError, ValueError, KeyError, IndexError, yaml.YAMLError) as exc:
        print(canonical({'status': 'ERROR', 'detail': str(exc)}), end='', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
