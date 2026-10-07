"""Closed JSON contracts and declarative element registration."""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
import yaml

from tools.element_checks import parse_check

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / 'config/elements/demo.yaml'
CONTRACTS = ('element-request', 'element-answer', 'search-request', 'search-answer', 'element-sequence')


def schema(name: str) -> dict:
    if name not in CONTRACTS:
        raise ValueError('Unsupported element contract')
    return json.loads((ROOT / 'schemas' / f'{name}.schema.json').read_text(encoding='utf-8'))


def validate_message(value: object, name: str) -> list[str]:
    # Deliberately omit rejected values (which may contain private material).
    return [f'{name}: {".".join(map(str, error.absolute_path)) or "$"}: {error.validator} failed'
            for error in Draft202012Validator(schema(name)).iter_errors(value)]


def require_message(value: object, name: str) -> None:
    errors = validate_message(value, name)
    if errors:
        raise ValueError('; '.join(errors))


def validate_sequence(sequence: dict) -> list[str]:
    errors = validate_message(sequence, 'element-sequence')
    if errors:
        return errors
    seen = set()
    kinds = {}
    for item in sequence['elements']:
        element_id = item['element_id']
        if element_id in seen:
            errors.append(f'{element_id}: duplicate element ID')
        bindings = item.get('inputs', {}).values() if item['kind'] == 'element' else [item['query']]
        for binding in bindings:
            reference = binding.get('answer')
            if 'search_result' in binding:
                reference = binding['search_result']['element_id']
                if kinds.get(reference) != 'search':
                    errors.append(f'{element_id}: search_result must reference an earlier search')
            if reference is not None and reference not in seen:
                errors.append(f'{element_id}: input must reference an earlier accepted answer')
        for check in item.get('checks', []):
            try:
                name, arg = parse_check(check)
                if name in {'reference_exists', 'exact_excerpt'} and arg not in item['inputs']:
                    errors.append(f'{element_id}: {name} requires a declared input key')
            except ValueError as exc:
                errors.append(f'{element_id}: {exc}')
        fmt = item.get('answer_format', {})
        if fmt.get('min_chars', 1) > fmt.get('max_chars', 1):
            errors.append(f'{element_id}: min_chars exceeds max_chars')
        seen.add(element_id)
        kinds[element_id] = item['kind']
    return errors


def load_sequence(path: Path = DEFAULT_REGISTRY) -> dict:
    try:
        sequence = yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as exc:
        raise ValueError('Registry must be valid YAML') from exc
    errors = validate_sequence(sequence)
    if errors:
        raise ValueError('; '.join(errors))
    sequence.setdefault('max_attempts', 5)
    return sequence


def validate_contracts() -> list[str]:
    errors = []
    for name in CONTRACTS:
        try:
            value = schema(name)
            Draft202012Validator.check_schema(value)
            if value.get('$id') != f'{name}/v1' or value.get('additionalProperties') is not False:
                errors.append(f'{name}: expected a closed versioned contract')
        except (OSError, ValueError, SchemaError) as exc:
            errors.append(f'{name}: invalid or missing schema ({type(exc).__name__})')
    if errors:
        return errors
    paths = sorted((ROOT / 'config/elements').glob('*.yaml'))
    if not paths:
        errors.append('config/elements: no registered sequence')
    for path in paths:
        try:
            errors.extend(f'{path.name}: {error}' for error in validate_sequence(yaml.safe_load(path.read_text(encoding='utf-8'))))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f'{path.name}: invalid registry ({type(exc).__name__})')
    return errors
