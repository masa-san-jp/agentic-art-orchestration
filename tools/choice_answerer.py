"""Two deterministic presentations of a choice, mapped back to its original meaning."""
from copy import deepcopy
import hashlib
import re
from tools.element_contracts import require_message


def orders(request):
    choices = request['answer_format']['choices']
    if len(choices) < 2:
        raise ValueError('Stability requires at least two choices')
    seed = '|'.join(str(request[k]) for k in ('run_id', 'element_id', 'attempt'))
    shift = 1 + int(hashlib.sha256(seed.encode()).hexdigest(), 16) % (len(choices) - 1)
    return [list(choices), choices[shift:] + choices[:shift]]


def presentation(request, order):
    """Numeric cards are relabelled, including the none option; categorical labels retain meaning."""
    changed = deepcopy(request)
    choices = request['answer_format']['choices']
    cards = request['inputs'].get('cards')
    numeric = isinstance(cards, dict) and set(cards).issubset(choices) and all(c.isdecimal() for c in choices)
    if numeric:
        mapping = dict(zip(choices, order))
        changed['inputs']['cards'] = {label: cards[original] for label, original in mapping.items() if original in cards}
        none = set(choices) - set(cards)
        if len(none) > 1:
            raise ValueError('Ambiguous numeric card choices')
        if none:
            original = next(iter(none))
            label = choices[order.index(original)]
            changed['instruction'] = re.sub(r'(?<![0-9])' + re.escape(original) + r'(?![0-9])', label, request['instruction'])
    else:
        changed['answer_format']['choices'] = list(order)
        descriptions = changed['inputs'].get('link_types')
        if isinstance(descriptions, dict):
            changed['inputs']['link_types'] = {key: descriptions[key] for key in order if key in descriptions}
            changed['inputs']['link_types'].update({key: value for key, value in descriptions.items() if key not in order})
    require_message(changed, 'element-request')
    return changed


def original_value(request, order, value):
    choices = request['answer_format']['choices']
    if value not in choices:
        raise ValueError('Choice response is outside the supplied options')
    cards = request['inputs'].get('cards')
    if isinstance(cards, dict) and set(cards).issubset(choices) and all(c.isdecimal() for c in choices):
        return order[choices.index(value)]
    return value


def check_observations(request, answer):
    """The engine checks observations itself, never trusts an accepted/stable flag."""
    observations = answer.get('choice_observations')
    is_judge = answer.get('answerer_kind', '').startswith('judge-')
    if observations is None and not is_judge:
        return []
    failures = [{'check': 'choice_stability', 'reason': 'Return two matching choices from the deterministic presentations.'}]
    if request['answer_format']['type'] != 'choice' or not isinstance(observations, list) or len(observations) != 2:
        return failures
    from tools.element import canonical
    try:
        expected = orders(request)
        values = []
        for row, order in zip(observations, expected):
            changed = presentation(request, order)
            digest = hashlib.sha256(canonical(changed).encode()).hexdigest()
            if row['order'] != order or row['request_sha256'] != digest:
                return failures
            values.append(original_value(request, order, row['value']))
        return [] if values[0] == values[1] == answer['value'] else failures
    except (KeyError, TypeError, ValueError):
        return failures
