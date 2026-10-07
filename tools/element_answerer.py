#!/usr/bin/env python3
"""Answer exactly one request using a deterministic fake or a configured local command."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--fake', action='store_true', help='synthetic demo only')
    mode.add_argument('--config', type=Path, help='local command argv and timeout, never a shell expression')
    args = parser.parse_args(argv)
    try:
        answerer = FakeAnswerer() if args.fake else LocalAnswerer(yaml.safe_load(args.config.read_text(encoding='utf-8')))
        sys.stdout.write(canonical(answerer.answer(json.load(sys.stdin))))
        return 0
    except (OSError, ValueError, KeyError, IndexError, yaml.YAMLError) as exc:
        print(canonical({'status': 'ERROR', 'detail': str(exc)}), end='', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
