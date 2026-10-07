"""Mechanical checks for a single value; no model or network calls."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from ipaddress import IPv6Address
import re
import unicodedata
from urllib.parse import urlsplit


class CheckConfigurationError(ValueError):
    pass


def valid_url(value: object) -> bool:
    if not isinstance(value, str) or re.search(r'\s', value):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if not host:
            return False
        if ':' in host:
            IPv6Address(host)
        else:
            ascii_host = host.encode('idna').decode('ascii').rstrip('.')
            if len(ascii_host) > 253 or any(
                re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) is None
                for label in ascii_host.split('.')
            ):
                return False
        return (parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and parsed.port != 0)
    except (ValueError, UnicodeError):
        return False


def parse_check(spec: str) -> tuple[str, str]:
    name, _, arg = spec.partition(':')
    plain = {'non_empty', 'ends_with_question', 'url_shape', 'url_in_ledger'}
    lists = {'contains_terms', 'forbidden', 'one_of'}
    keyed = {'reference_exists', 'exact_excerpt'}
    if name in plain and not arg and ':' not in spec:
        return name, arg
    if name in lists and arg and all(item.strip() for item in arg.split(',')):
        return name, arg
    if name in keyed and re.fullmatch(r'[A-Za-z0-9._-]+', arg):
        return name, arg
    if name in {'min_chars', 'max_chars'} and arg.isdigit() and int(arg) > 0:
        return name, arg
    if name == 'not_similar':
        try:
            if Decimal(0) < Decimal(arg) <= Decimal(1):
                return name, arg
        except InvalidOperation:
            pass
    raise CheckConfigurationError(f'unknown or malformed check: {spec}')


def _grams(value: str) -> set[str]:
    text = ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
    return {text[i:i + 2] for i in range(len(text) - 1)} or {text}


def too_similar(left: str, right: str, threshold: str) -> bool:
    """NFKC/casefold/space-normalized character-bigram Jaccard, exact decimal comparison."""
    a, b = _grams(left), _grams(right)
    numerator, denominator = Decimal(threshold).as_integer_ratio()
    return len(a & b) * denominator >= numerator * len(a | b)


def check_value(value: object, checks: list[str], *, inputs: dict,
                ledger: dict, previous_answers: dict) -> list[dict[str, str]]:
    text = value.get('reason', '') if isinstance(value, dict) else value
    failures = []
    # This invariant applies even when a definition forgets to list non_empty.
    if not isinstance(text, str) or not text.strip():
        failures.append({'check': 'non_empty', 'reason': 'Return a non-empty value or reason.'})
        return failures
    for spec in checks:
        name, arg = parse_check(spec)
        ok = True
        reason = 'Value does not satisfy this check.'
        if name == 'non_empty':
            ok = bool(text.strip())
        elif name == 'min_chars':
            ok = len(text) >= int(arg)
            reason = f'Use at least {arg} characters.'
        elif name == 'max_chars':
            ok = len(text) <= int(arg)
            reason = f'Use at most {arg} characters.'
        elif name == 'ends_with_question':
            ok = text.rstrip().endswith(('?', '？'))
            reason = 'End the question with ? or ？.'
        elif name == 'contains_terms':
            terms = [inputs.get(item, item) for item in arg.split(',')]
            ok = all(isinstance(term, str) and term.strip() and term in text for term in terms)
            reason = 'Include every required term (input key or literal).'
        elif name == 'forbidden':
            ok = all(term not in text for term in arg.split(','))
            reason = 'Remove the forbidden terms.'
        elif name == 'one_of':
            ok = text in arg.split(',')
            reason = 'Choose one of the listed values exactly.'
        elif name == 'reference_exists':
            ids = inputs.get(arg)
            ok = isinstance(ids, (list, dict)) and text in ids
            reason = 'Use an ID present in the supplied registry.'
        elif name in {'url_shape', 'url_in_ledger'}:
            ok = valid_url(text) and (name == 'url_shape' or text in ledger)
            reason = 'Use an HTTP(S) URL' + (' from the retrieved-source ledger.' if name == 'url_in_ledger' else '.')
        elif name == 'exact_excerpt':
            url = inputs.get(arg)
            source = ledger.get(url, {}) if isinstance(url, str) else {}
            body = source.get('body', '')
            # A quotation is an exact contiguous substring; no normalization.
            ok = bool(body) and text in body
            reason = 'Copy an exact contiguous passage from the retrieved body.'
        elif name == 'not_similar':
            old = [v.get('reason', '') if isinstance(v, dict) else v for v in previous_answers.values()]
            ok = all(not too_similar(text, v, arg) for v in old if isinstance(v, str) and v.strip())
            reason = 'The value is too similar to an already accepted answer.'
        if not ok:
            failures.append({'check': spec, 'reason': reason})
    return failures
