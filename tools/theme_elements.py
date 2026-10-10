"""Phase A v2 driver (docs/20261010-phase-a-v2-design.md): the program orders and checks, the answerer judges.

The program never decides which card is related. It shows every eligible card to the answerer in a
fixed, unbiased (sha256) order, window by window, and verifies every answer mechanically. Only
consent-approved derived exports enter this driver; hearing packets and raw responses never do.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from tools.card_sources import MAX_CARD_BYTES, MAX_EXCERPTS, PhaseABlocked, git_blob_source, normalize_text, verify_card
from tools.element import canonical
from tools.element_contracts import load_sequence
from tools.element_checks import valid_url
from tools.validate import validate_signal

REGISTRY = Path(__file__).resolve().parents[1] / 'config/elements/phase-a.yaml'
DOMAINS = ('art', 'market')
SIGNAL_KIND = {'art': 'art-history', 'market': 'marketing'}
WINDOW_SIZE = 8
MAX_FINALISTS = 5
RECENT_RUNS = 3
BUDGET_SLACK = 45
REQUEST_LIMIT = 4096
NONE = 'なし'
LINK_TYPES = {
    '同じ': '同じやり方・態度が両方にある',
    '逆': '一方がすることを、もう一方は反対のやり方でする',
    '答え': '一方が抱える困りごとに、もう一方のやり方が手段を与える',
    '背景': '一方が、もう一方の態度が生まれる時代や社会の条件になっている',
}
LINK_HINTS = {'同じ': '何が両方に共通するのか', '逆': '何が何に対して反対なのか',
              '答え': 'どの困りごとにどの手段が応えるのか', '背景': 'どの条件がどの態度を生んだのか'}
# Fixed table: the self model's own vocabulary never reaches an answerer.
FIELD_JA = {'tensions': '引っ張り合っていること', 'recurring_patterns': '繰り返し出る形', 'seeks': '求めていること',
            'avoids': '避けていること', 'protects': '守っていること', 'states': 'いまの状態', 'traits': 'ふだんの傾向'}
STAGE_JA = {'growing': '伸びている', 'emerging': '出始め', 'peak': 'ピーク'}
SELF_CONTEXTS = 'contexts'
COUNTED_STOPS = ('NO_PICK:', 'NO_CONFIRMED_LINK:')


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def seed(*parts) -> str:
    return hashlib.sha256(':'.join(str(part) for part in parts).encode('utf-8')).hexdigest()


def _size(inputs: dict) -> int:
    return len(canonical(inputs).encode('utf-8'))


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


# ---------------------------------------------------------------- 3. the self material

def materials(signals: list[dict]) -> list[dict]:
    """One material per self signal (a confirmed claim or pattern), never a fragment of a condition."""
    result = []
    for signal in signals:
        if signal['signal_kind'] != 'self':
            continue
        domain = signal['domain']['self_model']
        if domain['export_permitted'] is not True or not domain['consent_scope'].strip():
            raise PhaseABlocked('SELF_EXPORT_NOT_PERMITTED')
        sentences = [(field, value.strip()) for field in FIELD_JA for value in domain.get(field, [])
                     if isinstance(value, str) and value.strip()]
        if not sentences:
            continue
        field, statement = sentences[0]
        conditions = [value.strip() for value in domain.get(SELF_CONTEXTS, []) if isinstance(value, str) and value.strip()]
        text = f'本人の素材（{FIELD_JA[field]}）：{statement}'
        if conditions:
            text += f'\n条件：{"／".join(conditions)}'
        result.append({'signal_id': signal['signal_id'], 'field': field, 'statement': statement,
                       'condition': '／'.join(conditions) or None, 'text': text,
                       'ignored_items': len(sentences) - 1, 'source': deepcopy(signal['source']),
                       'evidence_refs': deepcopy(signal['evidence_refs']), 'consent_scope': domain['consent_scope']})
    return sorted(result, key=lambda item: item['signal_id'])


def past_runs(state_root: Path, run_id: str) -> list[dict]:
    """Runs that used a material: completed ones and the two legitimate "no link" stops (7.4)."""
    rows = []
    for path in sorted(state_root.glob('*/element-state.json')):
        if path.parent.name == run_id or path.is_symlink() or path.parent.is_symlink():
            continue
        state = json.loads(path.read_text(encoding='utf-8'))
        phase = state.get('context', {}).get('phase_a')
        if not isinstance(phase, dict) or phase.get('version') != 'v2':
            continue
        reason = (state.get('blocked') or {}).get('reason', '')
        if state.get('status') == 'COMPLETED' or (state.get('status') == 'BLOCKED' and reason.startswith(COUNTED_STOPS)):
            rows.append({'run_id': state['run_id'], 'requested_at': phase['requested_at'],
                         'signal_id': phase['material']['signal_id'], 'field': phase['material']['field'],
                         'adopted': deepcopy(phase.get('adopted', {}))})
    return sorted(rows, key=lambda row: (_parse_time(row['requested_at']), row['run_id']))


def choose_material(options: list[dict], runs: list[dict], pinned: str | None) -> tuple[dict, dict]:
    usage = {}
    group_usage = {}
    for row in runs:
        usage[row['signal_id']] = usage.get(row['signal_id'], 0) + 1
        group_usage[row['field']] = group_usage.get(row['field'], 0) + 1
    if pinned is not None:
        found = [item for item in options if item['signal_id'] == pinned]
        if not found:
            raise PhaseABlocked('SELF_SIGNAL_NOT_FOUND', signal_id=pinned)
        return found[0], {'rule': 'owner-pinned', 'use_count': usage.get(pinned, 0)}
    selected = min(options, key=lambda item: (usage.get(item['signal_id'], 0), group_usage.get(item['field'], 0),
                                              seed(item['signal_id'], usage.get(item['signal_id'], 0))))
    return selected, {'rule': 'least-used, least-used-group, sha256', 'use_count': usage.get(selected['signal_id'], 0)}


# ---------------------------------------------------------------- 4. cards and windows

def _label(signal: dict, kind: str) -> str | None:
    domain = signal['domain'][SIGNAL_KIND[kind].replace('-', '_')]
    label = domain.get('label_ja') or (domain.get('entity_labels') or [None])[0] if kind == 'art' else domain.get('label_ja')
    return label.strip() if isinstance(label, str) and label.strip() else None


def build_card(signal: dict, kind: str) -> dict | str:
    """The deterministic card, or the exclusion reason that explains why there is none."""
    domain = signal['domain'][SIGNAL_KIND[kind].replace('-', '_')]
    items = domain.get('card')
    if not items:
        return 'no_card_text'
    label = _label(signal, kind)
    if label is None:
        return 'no_label'
    head = (f'{label}（{domain["time"]}・{domain["geo"]}）：' if kind == 'art'
            else f'{label}（{STAGE_JA.get(domain["stage"], domain["stage"])}）：')
    texts = [normalize_text(item['text']) for item in items[:MAX_EXCERPTS]]
    while texts and len((head + ' / '.join(texts)).encode('utf-8')) > MAX_CARD_BYTES:
        texts.pop()
    if not texts:
        return 'card_too_large'
    source = signal['source']
    return {'card_id': signal['signal_id'], 'domain': kind, 'label': label, 'text': head + ' / '.join(texts),
            'excerpts': texts,
            'sources': [{'repository': source['repository'], 'commit': source['commit'],
                         'locator': item['source_locator'], 'blob_sha256': item['source_sha256']}
                        for item in items[:len(texts)]]}


def _eligibility(signal: dict, kind: str, requested_at: str) -> str | None:
    """None when the signal may be a candidate; otherwise the exclusion reason (4.3)."""
    method = signal.get('domain', {}).get('art_history', {}).get('method')
    sourced_draft = (kind == 'art' and signal['validity']['status'] == 'unknown' and signal['freshness']['status'] == 'current'
                     and (bool(signal['domain']['art_history'].get('content')) or bool(signal['domain']['art_history'].get('card'))
                          or (isinstance(method, dict) and bool(signal['evidence_refs']))))
    if signal['validity']['status'] != 'valid' and not sourced_draft:
        return 'not_current_or_valid'
    if signal['freshness']['status'] != 'current':
        return 'not_current_or_valid'
    if kind == 'market' and _parse_time(signal['domain']['marketing']['expires_at']) <= _parse_time(requested_at):
        return 'expired'
    return None


def _fits(phase: dict, ids: list[str], size: int) -> bool:
    return len(ids) <= size and _size(_card_inputs(phase, ids)) <= REQUEST_LIMIT


def _card_inputs(phase: dict, ids: list[str]) -> dict:
    return {'material': phase['material']['text'], 'link_types': LINK_TYPES,
            'cards': {str(index): phase['cards'][identifier]['text'] for index, identifier in enumerate(ids, 1)}}


def _chunks(phase: dict, ids: list[str], size: int) -> list[list[str]]:
    """Consecutive groups of at most ``size`` cards whose request stays inside the byte limit."""
    groups, current = [], []
    for identifier in ids:
        if current and not _fits(phase, [*current, identifier], size):
            groups.append(current)
            current = []
        current.append(identifier)
    return groups + ([current] if current else [])


def rank_matches(count: int, size: int = WINDOW_SIZE) -> int:
    """Upper bound of single-elimination matches among ``count`` picks (design 5.3)."""
    if count <= 1:
        return 0
    if count <= size:
        return 1
    groups = -(-count // size)
    return groups + rank_matches(groups, size)


def budget_cap(windows: dict, max_finalists: int, rank_size: int = WINDOW_SIZE) -> tuple[int, dict]:
    parts = {'screens': sum(len(rows) for rows in windows.values()),
             'rank': sum(rank_matches(len(rows), rank_size) for rows in windows.values()),
             'winner_replacements': 2 * (max_finalists - 1) * len(DOMAINS),
             'verification': ((max_finalists - 1) + 5) * len(DOMAINS), 'a7': 2, 'retry_slack': BUDGET_SLACK}
    return sum(parts.values()), parts


def initial_context(signals: list[dict], state_root: Path, run_id: str, *, requested_at: str,
                    workspace_root: Path | None = None, self_signal: str | None = None,
                    blob_source=None, window_size: int = WINDOW_SIZE, rank_size: int = WINDOW_SIZE,
                    max_finalists: int = MAX_FINALISTS,
                    recent_runs: int = RECENT_RUNS, cap: int | None = None) -> dict:
    identifiers = set()
    for signal in signals:
        errors = validate_signal(signal, 'phase-a.signal')
        if errors:
            raise ValueError(f'INVALID_NORMALIZED_SIGNAL: {len(errors)} validation errors')
        if signal['signal_id'] in identifiers:
            raise ValueError('DUPLICATE_SIGNAL_ID')
        identifiers.add(signal['signal_id'])
    options = materials(signals)
    if not options:
        raise PhaseABlocked('SELF_MODEL_EMPTY', next_action='self-model hearing (SEED_REQUIRED)')
    runs = past_runs(state_root, run_id)
    material, selection = choose_material(options, runs, self_signal)
    recent = runs[-recent_runs:] if recent_runs else []

    cards, order, exclusions, pinned = {}, {}, {}, []
    for kind in DOMAINS:
        counts = {}
        candidates = []
        recently = {row['adopted'].get(kind) for row in recent}
        for signal in signals:
            if signal['signal_kind'] != SIGNAL_KIND[kind]:
                continue
            reason = _eligibility(signal, kind, requested_at)
            card = None
            if reason is None:
                card = build_card(signal, kind)
                reason = card if isinstance(card, str) else None
            if reason is None and signal['signal_id'] in recently:
                reason = 'recently_adopted'
            if reason:
                counts[reason] = counts.get(reason, 0) + 1
            else:
                candidates.append((signal, card))
        exclusions[kind] = {'eligible': len(candidates), 'excluded': dict(sorted(counts.items())),
                            'recently_adopted_ids': sorted(i for i in recently if i)}
        if not candidates:
            raise PhaseABlocked(f'{kind.upper()}_NO_ELIGIBLE_CARDS', excluded=dict(sorted(counts.items())))
        if blob_source is None and workspace_root is not None:
            blob_source = git_blob_source(workspace_root)
        for signal, card in candidates:
            if blob_source is None:
                raise PhaseABlocked('CARD_SOURCE_MISMATCH', signal_id=signal['signal_id'], detail='no pinned checkout to verify against')
            for item in signal['domain'][SIGNAL_KIND[kind].replace('-', '_')]['card'][:len(card['excerpts'])]:
                verify_card(signal, item, blob_source)
            cards[card['card_id']] = card
            pinned.append(deepcopy(signal))
        order[kind] = sorted(cards_of(cards, kind), key=lambda identifier: seed(material['signal_id'], selection['use_count'], identifier))

    phase = {'version': 'v2', 'requested_at': requested_at, 'material': material, 'material_selection': selection,
             'cards': cards, 'order': order, 'exclusions': exclusions, 'window_size': window_size, 'rank_size': rank_size,
             'max_finalists': max_finalists, 'windows': {}, 'window_of': {}, 'rank_matches': {kind: [] for kind in DOMAINS},
             'finalists': {kind: {} for kind in DOMAINS}, 'trials': {}, 'adopted': {}}
    for kind in DOMAINS:
        phase['windows'][kind] = _chunks(phase, order[kind], window_size)
        if any(not _fits(phase, [identifier], window_size) for identifier in order[kind]):
            raise PhaseABlocked('REQUEST_TOO_LARGE', element_id=f'A4.{kind}.screen.01')
        for index, window in enumerate(phase['windows'][kind]):
            phase['window_of'].update({identifier: index for identifier in window})
    total, parts = budget_cap(phase['windows'], max_finalists, rank_size)
    phase['budget'] = {'cap': cap if cap is not None else total, 'computed': total, 'parts': parts,
                       'override': cap is not None}
    selected_self = [deepcopy(signal) for signal in signals if signal['signal_id'] == material['signal_id']]
    for signal in selected_self:
        signal['domain']['self_model'].pop('raw_voice_locator', None)
    phase['signals'] = selected_self + pinned
    return {'phase_a': phase}


def cards_of(cards: dict, kind: str) -> list[str]:
    return [identifier for identifier, card in cards.items() if card['domain'] == kind]


# ---------------------------------------------------------------- 5. the element sequence

def _definition(phase: dict, name: str, element_id: str, inputs: dict, *, hidden=None, link_type=None, choices=None) -> dict:
    template = deepcopy(phase['templates'][name])
    template['element_id'] = element_id
    template['inputs'] = {key: {'literal': value} for key, value in inputs.items()}
    if hidden is not None:
        template['hidden'] = hidden
    if link_type is not None:
        template['instruction'] = template['instruction'].replace('{link_type}', link_type)
    if choices is not None:
        template['answer_format'] = {'type': 'choice', 'choices': choices}
    return template


def _attempts(state: dict, element_id: str) -> int:
    return sum(1 for row in state['history'] if row['element_id'] == element_id)


def _family(element_id: str) -> str:
    parts = element_id.split('.')
    return '.'.join(parts[:3] if parts[0] == 'A4' else parts[:2] if parts[0] == 'A5' else parts[:1])


def _block(state: dict, reason: str, **details) -> None:
    state.update(status='BLOCKED', pending=None, blocked={'reason': reason, **details})


def _gate(state: dict) -> bool:
    """The run budget (5.7); True when the run was stopped."""
    budget = state['context']['phase_a']['budget']
    if len(state['history']) < budget['cap']:
        return False
    breakdown = {}
    for row in state['history']:
        breakdown[_family(row['element_id'])] = breakdown.get(_family(row['element_id']), 0) + 1
    _block(state, 'RUN_BUDGET_EXHAUSTED', cap=budget['cap'], used=len(state['history']), breakdown=dict(sorted(breakdown.items())))
    return True


def advance(state: dict) -> None:
    """Enforce the budget before every request and extend the sequence only at an accepted checkpoint."""
    if state['index'] < len(state['sequence']['elements']):
        _gate(state)
        return
    step = _plan(state)
    if step[0] == 'blocked':
        _block(state, step[1], **step[2])
        return
    if step[0] == 'done' or _gate(state):
        return
    _, definition, meta = step
    element_id = definition['element_id']
    attempt = _attempts(state, element_id) + 1
    if attempt > state['sequence']['max_attempts']:
        _block(state, 'ELEMENT_ATTEMPTS_EXHAUSTED', element_id=element_id, attempt=attempt - 1,
               last_failure=(meta or {}).get('previous_failure') or state.get('previous_failure') or [])
        return
    if _size({key: binding['literal'] for key, binding in definition['inputs'].items()}) > REQUEST_LIMIT:
        _block(state, 'REQUEST_TOO_LARGE', element_id=element_id)
        return
    state['sequence']['elements'].append(definition)
    state['attempt'] = attempt
    state['previous_failure'] = (meta or {}).get('previous_failure')


def _plan(state: dict):
    answers = state['answers']
    phase = state['context']['phase_a']
    for kind in DOMAINS:
        step = _domain(state, kind)
        if step[0] != 'adopted':
            return step
    parts = {kind: _quotes(state, kind) for kind in DOMAINS}
    quotes = {'self_quote': parts['art']['self_quote'], 'art_card_quote': parts['art']['card_quote'],
              'market_card_quote': parts['market']['card_quote']}
    sentences = {kind: answers[f'A5.{kind}.{phase["adopted_k"][kind]}.sentence'] for kind in DOMAINS}
    if 'A7.overlap' not in answers:
        return ('element', _definition(phase, 'A7.overlap', 'A7.overlap', {
            'material_statement': phase['material']['statement'], 'art_sentence': sentences['art'],
            'market_sentence': sentences['market']}, hidden=quotes), None)
    if 'A7.question' not in answers:
        return ('element', _definition(phase, 'A7.question', 'A7.question', {
            'overlap': answers['A7.overlap'], 'self_quote': quotes['self_quote'],
            'art_card_quote': quotes['art_card_quote'], 'market_card_quote': quotes['market_card_quote']}), None)
    return ('done',)


def _quotes(state: dict, kind: str) -> dict:
    k = state['context']['phase_a']['adopted_k'][kind]
    return {'self_quote': state['answers'][f'A5.{kind}.{k}.self-quote'], 'card_quote': state['answers'][f'A5.{kind}.{k}.card-quote']}


def _domain(state: dict, kind: str):
    phase, answers = state['context']['phase_a'], state['answers']
    windows = phase['windows'][kind]
    picks = []
    for number, window in enumerate(windows, 1):
        element_id = f'A4.{kind}.screen.{number:02d}'
        if element_id not in answers:
            return ('element', _definition(phase, 'A4.screen', element_id, _card_inputs(phase, window),
                                           choices=[str(index) for index in range(len(window) + 1)]), None)
        if int(answers[element_id]):
            picks.append(window[int(answers[element_id]) - 1])
    if not picks:
        return ('blocked', f'NO_PICK:{kind}', {'windows': len(windows), 'cards': len(phase['order'][kind])})
    eliminated = []
    for k in range(1, phase['max_finalists'] + 1):
        if len(eliminated) == len(picks):
            break
        step = _winner(state, kind, picks, eliminated)
        if step[0] != 'winner':
            return step
        winner = step[1]
        phase['finalists'][kind][str(k)] = winner
        verdict = _verify(state, kind, k, winner)
        if verdict[0] == 'adopted':
            phase.setdefault('adopted_k', {})[kind] = k
            phase['adopted'][kind] = winner
            return verdict
        if verdict[0] != 'none':
            return verdict
        eliminated.append(winner)
    return ('blocked', f'NO_CONFIRMED_LINK:{kind}', {
        'finalists': [{'card_id': phase['finalists'][kind][str(k)], 'answer': answers.get(f'A5.{kind}.{k}.type')}
                      for k in range(1, len(phase['finalists'][kind]) + 1)]})


def _winner(state: dict, kind: str, picks: list[str], eliminated: list[str]):
    """Single elimination over the picks.

    The first-round groups are fixed by the original picks; a replaced winner only leaves its group,
    so that group and the later rounds above it are replayed and every other match is reused.
    """
    phase, answers = state['context']['phase_a'], state['answers']
    ledger = phase['rank_matches'][kind]
    size = phase['rank_size']
    position = {identifier: index for index, identifier in enumerate(phase['order'][kind])}
    groups = [[identifier for identifier in group if identifier not in eliminated] for group in _chunks(phase, picks, size)]
    groups = [group for group in groups if group]
    round_number = 1
    while not (len(groups) == 1 and len(groups[0]) == 1):
        if round_number > 1 and len(groups) > 1 and all(len(group) == 1 for group in groups):
            return ('blocked', 'REQUEST_TOO_LARGE', {'element_id': f'A4.{kind}.rank.{round_number}.1'})
        advancing = []
        for number, group in enumerate(groups, 1):
            if len(group) == 1:
                advancing.append(group[0])
                continue
            match = next((row for row in ledger if row['members'] == group), None)
            if match is None:
                base = f'A4.{kind}.rank.{round_number}.{number}'
                taken = {row['element_id'] for row in ledger}
                element_id = base if base not in taken else next(f'{base}.v{n}' for n in range(2, 99) if f'{base}.v{n}' not in taken)
                match = {'element_id': element_id, 'members': list(group)}
                ledger.append(match)
            if match['element_id'] not in answers:
                return ('element', _definition(phase, 'A4.rank', match['element_id'], _card_inputs(phase, group),
                                               choices=[str(index) for index in range(1, len(group) + 1)]), None)
            match['winner'] = group[int(answers[match['element_id']]) - 1]
            advancing.append(match['winner'])
        groups = _chunks(phase, sorted(advancing, key=position.__getitem__), size)
        round_number += 1
    return ('winner', groups[0][0])


def _verify(state: dict, kind: str, k: int, winner: str):
    phase, answers = state['context']['phase_a'], state['answers']
    card, material = phase['cards'][winner], phase['material']
    prefix = f'A5.{kind}.{k}'
    if f'{prefix}.type' not in answers:
        return ('element', _definition(phase, 'A5.type', f'{prefix}.type', {
            'material': material['text'], 'card': card['text'], 'link_types': LINK_TYPES}), None)
    link_type = answers[f'{prefix}.type']
    if link_type == NONE:
        return ('none',)
    if f'{prefix}.card-quote' not in answers:
        return ('element', _definition(phase, 'A5.card-quote', f'{prefix}.card-quote', {
            'card_excerpts': ' / '.join(card['excerpts']), 'link_type': link_type},
            hidden={'label': card['label']}, link_type=link_type), None)
    if f'{prefix}.self-quote' not in answers:
        return ('element', _definition(phase, 'A5.self-quote', f'{prefix}.self-quote', {
            'material_statement': material['statement'], 'link_type': link_type}, link_type=link_type), None)
    window = phase['windows'][kind][phase['window_of'][winner]]
    if f'{prefix}.sentence' not in answers:
        trials = phase['trials'].get(f'{kind}.{k}', [])
        failure = None
        if trials:
            failure = [{'check': 'link_type_probe',
                        'reason': f'この文は『{link_type}』の関係として読めませんでした。{LINK_HINTS[link_type]}を書いてください。'}]
        return ('element', _definition(phase, 'A5.sentence', f'{prefix}.sentence', {
            'self_quote': answers[f'{prefix}.self-quote'], 'card_quote': answers[f'{prefix}.card-quote'],
            'card_label': card['label'], 'link_type': link_type, 'link_type_description': LINK_TYPES[link_type]},
            hidden={'specificity': {'card': card['text'], 'others': [phase['cards'][i]['text'] for i in window if i != winner]}},
            link_type=link_type), {'previous_failure': failure})
    sentence = answers[f'{prefix}.sentence']
    if f'{prefix}.sentence.probe' not in answers:
        masked = sentence
        for text in sorted({answers[f'{prefix}.card-quote'], card['label'], *card['excerpts']}, key=len, reverse=True):
            masked = masked.replace(text, '＿＿')
        return ('element', _definition(phase, 'A5.sentence.probe', f'{prefix}.sentence.probe', {
            'sentence_masked': masked, 'link_types': LINK_TYPES}, hidden={'expected': link_type}), None)
    from tools.element_checks import check_value
    reading = answers[f'{prefix}.sentence.probe']
    if not check_value(reading, ['expected_choice:expected'], inputs={'expected': link_type}, ledger={}, previous_answers={}):
        return ('adopted', winner)
    # The sentence, not the reading, failed: keep the trial and ask for the sentence again.
    phase['trials'].setdefault(f'{kind}.{k}', []).append({'sentence': sentence, 'probe_answer': reading, 'expected': link_type})
    answers.pop(f'{prefix}.sentence')
    answers.pop(f'{prefix}.sentence.probe')
    return _verify(state, kind, k, winner)


def start(engine, signals: list[dict], *, requested_at: str, workspace_root: Path | None = None,
          self_signal: str | None = None, blob_source=None, budget: int | None = None,
          window_size: int = WINDOW_SIZE, rank_size: int = WINDOW_SIZE) -> dict:
    if engine.path.exists():
        return engine.next()
    sequence = load_sequence(REGISTRY)
    templates = {item['element_id']: deepcopy(item) for item in sequence['elements']}
    context = initial_context(signals, engine.directory.parent, engine.run_id, requested_at=requested_at,
                              workspace_root=workspace_root, self_signal=self_signal, blob_source=blob_source,
                              window_size=window_size, rank_size=rank_size, cap=budget)
    phase = context['phase_a']
    phase['templates'] = templates
    first = phase['windows']['art'][0]
    sequence['elements'] = [_definition(phase, 'A4.screen', 'A4.art.screen.01', _card_inputs(phase, first),
                                        choices=[str(index) for index in range(len(first) + 1)])]
    return engine.next(sequence=sequence, context=context)


# ---------------------------------------------------------------- 7. provenance

def provenance(state: dict) -> dict:
    phase, answers = state['context']['phase_a'], state['answers']
    signals = {signal['signal_id']: signal for signal in phase['signals']}
    positions = {}
    screens, ranks, checks = {}, {}, {}
    for kind in DOMAINS:
        screens[kind] = []
        for number, window in enumerate(phase['windows'][kind], 1):
            element_id = f'A4.{kind}.screen.{number:02d}'
            choice = int(answers[element_id]) if element_id in answers else None
            positions[str(choice)] = positions.get(str(choice), 0) + 1
            screens[kind].append({'element_id': element_id, 'window': list(window), 'choice': choice,
                                  'picked': window[choice - 1] if choice else None})
        ranks[kind] = [{'element_id': row['element_id'], 'members': list(row['members']), 'winner': row.get('winner')}
                       for row in phase['rank_matches'][kind]]
        checks[kind] = {}
        for k, card_id in phase['finalists'][kind].items():
            prefix = f'A5.{kind}.{k}'
            checks[kind][k] = {'card_id': card_id, 'type': answers.get(f'{prefix}.type'),
                               'card_quote': answers.get(f'{prefix}.card-quote'), 'self_quote': answers.get(f'{prefix}.self-quote'),
                               'sentence': answers.get(f'{prefix}.sentence'), 'probe': answers.get(f'{prefix}.sentence.probe'),
                               'trials': deepcopy(phase['trials'].get(f'{kind}.{k}', [])),
                               'attempts': {part: sum(1 for row in state['history'] if row['element_id'] == f'{prefix}.{part}')
                                            for part in ('type', 'card-quote', 'self-quote', 'sentence', 'sentence.probe')}}
    breakdown = {}
    for row in state['history']:
        breakdown[_family(row['element_id'])] = breakdown.get(_family(row['element_id']), 0) + 1
    return {'contract_version': 'phase-a-provenance/v2', 'run_id': state['run_id'],
            'source_repository': state['source_repository'], 'source_commit': state['source_commit'],
            'material': deepcopy(phase['material']), 'material_selection': deepcopy(phase['material_selection']),
            'exclusions': deepcopy(phase['exclusions']),
            'cards': {identifier: {key: deepcopy(card[key]) for key in ('text', 'excerpts', 'sources')}
                      for identifier, card in phase['cards'].items()},
            'screens': screens, 'position_distribution': dict(sorted(positions.items())), 'rank': ranks,
            'verification': checks, 'adopted': deepcopy(phase['adopted']),
            'not_adopted': {kind: [{'card_id': row['card_id'], 'answer': row['type']} for row in checks[kind].values()
                                   if row['card_id'] != phase['adopted'][kind]] for kind in DOMAINS},
            'picked_not_finalist': {kind: [row['picked'] for row in screens[kind] if row['picked']
                                           and row['picked'] not in phase['finalists'][kind].values()] for kind in DOMAINS},
            'overlap': answers['A7.overlap'], 'creative_question': answers['A7.question'],
            'inference': {'count': len(state['history']), 'cap': phase['budget']['cap'], 'breakdown': dict(sorted(breakdown.items())),
                          'answerers': sorted({row['answerer_kind'] for row in state['history'] if 'answerer_kind' in row})},
            'selected': {SIGNAL_KIND[kind]: {'signal': deepcopy(signals[phase['adopted'][kind]])} for kind in DOMAINS}}


def reference_aliases(request: dict) -> list[dict]:
    """Retain real public ARK-like URLs without the receiver's path ambiguity.

    Other references continue through the native security checker unchanged.
    Never hide a query/signed URL or a public-boundary finding behind a hash.
    """
    from tools.security import scan_public_projection
    aliases = []
    for reference in request['references']:
        uri = reference['uri']
        if not uri.startswith(('https://', 'http://')):
            continue
        parsed = urlsplit(uri)
        if ':/' not in parsed.path or parsed.query or parsed.fragment:
            continue
        if not valid_url(uri) or scan_public_projection({'uri': uri}):
            raise ValueError('UNSAFE_PUBLIC_REFERENCE_ALIAS')
        alias = 'urn:orchestration:phase-a-reference:sha256:' + hashlib.sha256(uri.encode('utf-8')).hexdigest()
        aliases.append({**deepcopy(reference), 'request_uri': alias})
        reference['uri'] = alias
    return aliases


def write_request(engine, output: Path, *, slug: str, title: str, research_root: Path | None) -> Path:
    """Use the native closed RR schema and reference structured provenance by URI."""
    from tools.build_research_request import build_request, _next_request_id
    with engine._locked():
        state = engine._read()
        if state['status'] != 'COMPLETED':
            raise ValueError('Phase A is not completed')
        output.mkdir(parents=True, exist_ok=True)
        origin = provenance(state)
        origin_path = output / 'phase-a-provenance.json'
        selected = origin['selected']
        source_signals = {signal['signal_id']: signal for signal in state['context']['phase_a']['signals']}
        ids = [('self', origin['material']['signal_id'])] + [(kind, selected[kind]['signal']['signal_id']) for kind in SIGNAL_KIND.values()]
        proposition = {'proposition_id': f"phase-a:{engine.run_id}", 'structured_output': {
            'template': origin['creative_question'],
            'slots': {kind: {'signal_kind': kind, 'signal_id': identifier} for kind, identifier in ids}}}
        if 'request_id' not in state:
            state['request_id'] = _next_request_id(output, research_root=research_root)
            engine._save(state)
        request = build_request(proposition, source_signals, request_id=state['request_id'], slug=slug,
                                title=title, requested_at=state['context']['phase_a']['requested_at'],
                                commit=state['source_commit'], deadline=None, creator_id=None, creative_question=origin['creative_question'])
        # Never invoke the legacy slot/template formatter on inferred question text.
        request['intent']['creative_question'] = origin['creative_question']
        # The overlap sentence is the proposition candidate the question was derived from.
        request['intent']['purpose'] += f" 命題の候補: {origin['overlap']}"
        origin['reference_aliases'] = reference_aliases(request)
        origin_bytes = canonical(origin)
        origin_uri = f"urn:orchestration:phase-a:{engine.run_id}:sha256:{digest(origin)}"
        request['source']['artifact_uri'] = origin_uri
        request['references'].append({'label': 'phase-a-provenance.json: material, cards, screening, verification and the question',
                                      'uri': origin_uri, 'rights_status': 'APPROVED_REFERENCE'})

        destination = output / f"{state['request_id']}.yaml"
        for path, text in ((origin_path, origin_bytes), (destination, yaml.safe_dump(request, sort_keys=False, allow_unicode=True))):
            if path.exists():
                if path.read_text(encoding='utf-8') != text:
                    raise ValueError('Existing Phase A research artifact differs')
            else:
                with path.open('x', encoding='utf-8') as handle:
                    handle.write(text)
                path.chmod(0o600)
        return destination
