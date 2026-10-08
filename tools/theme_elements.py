"""Phase A's deterministic material, matching and selection steps for the shared Engine.

Only consent-approved derived exports enter this driver. Hearing packets and raw
responses belong to the Self Model owner and never enter this context.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import yaml
from urllib.parse import urlsplit

from tools.element import canonical
from tools.element_contracts import load_sequence
from tools.element_checks import source_terms, valid_url
from tools.validate import validate_signal

REGISTRY = Path(__file__).resolve().parents[1] / 'config/elements/phase-a.yaml'
METADATA = {'consent_scope', 'export_permitted', 'raw_voice_locator'}
DOMAINS = ('art-history', 'marketing')


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def materials(signals: list[dict]) -> list[dict]:
    """Every nonempty exported content item, excluding transport/consent metadata."""
    result = []
    for signal in signals:
        if signal['signal_kind'] != 'self':
            continue
        domain = signal['domain']['self_model']
        if domain['export_permitted'] is not True or not domain['consent_scope'].strip():
            raise ValueError('SELF_EXPORT_NOT_PERMITTED')
        for attribute, values in sorted(domain.items()):
            if attribute in METADATA:
                continue
            for value in values if isinstance(values, list) else [values]:
                if isinstance(value, str) and value.strip():
                    result.append({'material_id': digest([signal['signal_id'], attribute, value]),
                                   'signal_id': signal['signal_id'], 'attribute': attribute,
                                   'text': value, 'source': deepcopy(signal['source']),
                                   'evidence_refs': deepcopy(signal['evidence_refs']),
                                   'consent_scope': domain['consent_scope']})
    # Duplicated items in an export are one addressable piece of material.
    return sorted({item['material_id']: item for item in result}.values(),
                  key=lambda item: (item['attribute'], item['text'], item['signal_id']))


def signal_body(signal: dict, targets: dict | None = None, public: dict | None = None) -> str:
    if signal['signal_kind'] == 'art-history':
        domain = signal['domain']['art_history']
        content = domain.get('content', [])
        if content:
            return '\n'.join(item['text'] for item in content)
        # Legacy method pins already carry sourced operational descriptions.
        # Names, ID strings, relation labels and envelope boilerplate are never
        # substitutes for the missing historical content.
        parts = []
        method = domain.get('method', {})
        if domain.get('source_refs'):
            for key in ('fixes', 'varies', 'requires'):
                parts.extend(method.get(key, []))
    else:
        parts = [signal['statement']]
        # The envelope's basis is the exported evidence summary, not a locator.
        if public and signal['signal_id'] in public.get('evidence', {}):
            parts.append(public['evidence'][signal['signal_id']]['text'])
        parts.append(signal['certainty']['basis'])
    return '\n'.join(part for part in parts if part.strip())


def excerpt(body: str, limit=900) -> str:
    return body.encode('utf-8')[:limit].decode('utf-8', errors='ignore')


def matching_terms(value: str) -> set[str]:
    """Do not reward shingles spanning common Japanese grammatical boundaries."""
    text = unicodedata.normalize('NFKC', value)
    return set().union(*(source_terms(part) for part in re.split(r'まで|から|[のをがにはとでな]', text)))


def ranked(operation: str | list[str], signals: list[dict], kind: str, public: dict | None = None) -> list[dict]:
    operations = [operation] if isinstance(operation, str) else operation
    terms = set().union(*(matching_terms(word) for word in operations))
    targets = {entity: signal for signal in sorted(signals, key=lambda s: s['signal_id'], reverse=True)
               if signal['signal_kind'] == 'art-history' for entity in signal['source']['entity_ids']}
    rows = []
    for signal in signals:
        if signal['signal_kind'] != kind:
            continue
        body = signal_body(signal, targets, public)
        relations = signal.get('domain', {}).get('art_history', {}).get('relations', [])
        relation_sources = [{'signal_id': targets[rel['target_entity_id']]['signal_id'],
                             'source': deepcopy(targets[rel['target_entity_id']]['source'])}
                            for rel in relations if rel['target_entity_id'] in targets]
        public_refs = []
        if public:
            public_refs.extend(public['targets'][rel['target_entity_id']]['source'] for rel in relations if rel['target_entity_id'] in public.get('targets', {}))
            if signal['signal_id'] in public.get('evidence', {}):
                public_refs.append(public['evidence'][signal['signal_id']]['source'])
        # URL slugs and Markdown link targets identify evidence, not content.
        scoring_body = re.sub(r'\[([^\]]+)\]\([^\n)]*\)', r'\1', body)
        scoring_body = re.sub(r'https?://[^\s<>]+', ' ', scoring_body)
        if kind == 'art-history':
            scoring_body = unicodedata.normalize('NFKC', scoring_body).casefold()
            for label in signal['domain']['art_history'].get('entity_labels', []):
                scoring_body = scoring_body.replace(unicodedata.normalize('NFKC', label).casefold(), ' ')
        overlap = terms & matching_terms(scoring_body)
        evidence = {(ref['locator'], ref['kind']) for ref in signal['evidence_refs']}
        rows.append({'signal_id': signal['signal_id'], 'text': body,
                     'score': sum(len(term) for term in overlap),
                     'matched_terms': sorted(overlap),
                     'score_breakdown': {term: len(term) for term in sorted(overlap)},
                     'evidence_strength': sum(kind == 'primary' for _, kind in evidence),
                     'evidence_count': len(evidence), 'relation_sources': relation_sources, 'public_source_refs': public_refs})
    return sorted(rows, key=lambda row: (-row['score'], row['signal_id']))


def initial_context(signals: list[dict], state_root: Path, run_id: str, *, k=5,
                    requested_at: str, intent: str | None = None) -> dict:
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError('Phase A k must be a positive integer')
    identifiers = set()
    eligible = []
    excluded = []
    for signal in signals:
        errors = validate_signal(signal, 'phase-a.signal')
        if errors:
            raise ValueError(f'INVALID_NORMALIZED_SIGNAL: {len(errors)} validation errors')
        if signal['signal_id'] in identifiers:
            raise ValueError('DUPLICATE_SIGNAL_ID')
        identifiers.add(signal['signal_id'])
        method = signal.get('domain', {}).get('art_history', {}).get('method')
        sourced_draft_method = (signal['signal_kind'] == 'art-history' and isinstance(method, dict)
                                and signal['validity']['status'] == 'unknown'
                                and signal['freshness']['status'] == 'current' and bool(signal['evidence_refs']))
        sourced_draft_content = (signal['signal_kind'] == 'art-history'
                                 and bool(signal['domain']['art_history'].get('content'))
                                 and signal['validity']['status'] == 'unknown'
                                 and signal['freshness']['status'] == 'current')
        if (signal['validity']['status'] != 'valid' and not sourced_draft_method and not sourced_draft_content) or (signal['signal_kind'] == 'marketing' and signal['freshness']['status'] != 'current') or (signal['signal_kind'] == 'art-history' and signal['freshness']['status'] != 'current'):
            excluded.append({'signal_id': signal['signal_id'], 'reason': 'SIGNAL_NOT_CURRENT_OR_VALID'})
            continue
        if signal['signal_kind'] == 'marketing':
            expires = signal['domain']['marketing']['expires_at']
            if datetime.fromisoformat(expires.replace('Z', '+00:00')) <= datetime.fromisoformat(requested_at.replace('Z', '+00:00')):
                excluded.append({'signal_id': signal['signal_id'], 'reason': 'MARKET_SIGNAL_EXPIRED'})
                continue
        eligible.append(signal)
    signals = eligible
    options = materials(signals)
    if not options:
        raise ValueError('SELF_MODEL_EMPTY')
    if any(not any(s['signal_kind'] == kind for s in signals) for kind in DOMAINS):
        raise ValueError('THEME_DOMAIN_EMPTY')
    usage = Counter()
    operations = []
    for path in sorted(state_root.glob('*/element-state.json')):
        if path.parent.name == run_id or path.is_symlink() or path.parent.is_symlink():
            continue
        previous = json.loads(path.read_text(encoding='utf-8'))
        phase = previous.get('context', {}).get('phase_a')
        if isinstance(phase, dict) and 'A3.operation' in previous.get('answers', {}):
            usage[phase['material']['material_id']] += 1
            operations.extend(value for key, value in previous['answers'].items()
                              if key == 'A3.operation' or key.startswith('A3.operation.'))
    normalized_intent = None
    if intent is not None:
        if not isinstance(intent, str):
            raise ValueError('INTENT_MUST_BE_TEXT')
        normalized_intent = ' '.join(unicodedata.normalize('NFKC', intent).casefold().split())
        if not normalized_intent:
            raise ValueError('INTENT_MUST_NOT_BE_EMPTY')
    intent_terms = source_terms(normalized_intent) if normalized_intent else set()
    def intent_score(item):
        return sum(len(term) for term in intent_terms & source_terms(item['text']))
    selected = min(options, key=lambda item: (usage[item['material_id']], -intent_score(item), item['attribute'], item['text'], item['signal_id']))
    selection = {'rule': 'least-used, optional-intent-overlap, attribute/text/signal-ID',
                 'use_count': usage[selected['material_id']], 'intent_score': intent_score(selected),
                 'intent_sha256': hashlib.sha256(normalized_intent.encode()).hexdigest() if normalized_intent else None}
    # Copy immutable normalized signals for same-run resume, remove even opaque
    # raw voice references from the theme driver's retained context.
    pinned = deepcopy(signals)
    for signal in pinned:
        if signal['signal_kind'] == 'self':
            signal['domain']['self_model'].pop('raw_voice_locator', None)
    return {'material': excerpt(selected['text']), 'phase_a': {
        'material': selected, 'material_selection': selection, 'material_ids': [item['material_id'] for item in options],
        'signals': pinned, 'k': k, 'requested_at': requested_at,
        'prior_operations': operations, 'excluded_signals': excluded, 'rankings': {}, 'offsets': {kind: 0 for kind in DOMAINS},
        'judgements': {}, 'selected': {}}}


def _definition(templates: dict, name: str, element_id: str, inputs: dict) -> dict:
    template = deepcopy(templates[name])
    template['element_id'] = element_id
    template['inputs'] = {key: {'literal': value} for key, value in inputs.items()}
    return template


def advance(state: dict) -> None:
    """Extend the common sequence only at an accepted checkpoint, under its lock."""
    phase = state['context']['phase_a']
    answers = state['answers']
    if 'A7.central-question' in answers:
        return
    if not phase['rankings']:
        operations = [value for key, value in answers.items() if key == 'A3.operation' or key.startswith('A3.operation.')]
        rankings = {kind: ranked(operations, phase['signals'], kind, phase.get('public_sources')) for kind in DOMAINS}
        zero = [kind for kind, rows in rankings.items() if not any(row['score'] > 0 for row in rows)]
        history = phase.setdefault('matching_history', [])
        history.append({'operations': operations, 'zero_score_domains': zero,
                        'diagnostics': {kind: {'candidate_count': len(rows),
                                              'content_count': sum(bool(row['text']) for row in rows),
                                              'reason': ('MISSING_SOURCED_CONTENT' if not any(row['text'] for row in rows)
                                                         else 'NO_CONTENT_TERM_OVERLAP') if kind in zero else None}
                                        for kind, rows in rankings.items()},
                        'reason': 'NO_CONTENT_TERM_OVERLAP' if zero else None,
                        'rankings': {kind: [{key: row[key] for key in ('signal_id', 'score', 'matched_terms', 'score_breakdown')}
                                            for row in rows] for kind, rows in rankings.items()}})
        if zero:
            failure = [{'check': 'content_match_required',
                        'reason': 'All content scores are zero in: ' + ', '.join(zero)}]
            if len(operations) >= state['sequence']['max_attempts']:
                state.update(status='BLOCKED', pending=None, blocked={
                    'element_id': 'A4.matching', 'attempt': len(operations), 'last_failure': failure})
                return
            template = phase.get('operation_template', state['sequence']['elements'][0])
            added = _definition({'operation': template}, 'operation', f'A3.operation.{len(operations) + 1}', {
                'material': excerpt(phase['material']['text']),
                'prior_operations': '、'.join(operations)})
            added['instruction'] = '本文との一致が全件0点でした。本人の素材から、前の語とは異なる操作・状態を表す短い語をもう一つ返してください。'
            state['previous_failure'] = failure
            state['sequence']['elements'].append(added)
            return
        phase['rankings'] = {kind: [row for row in rows if row['score'] > 0] for kind, rows in rankings.items()}
    for kind in DOMAINS:
        rows = phase['rankings'][kind]
        # Complete this window before making any selection; preserve no reasons too.
        evaluated = []
        for index, row in enumerate(rows[:phase['offsets'][kind]]):
            identifier = f'A5.{kind}.{index + 1}'
            if identifier in answers:
                phase['judgements'][identifier] = {'signal_id': row['signal_id'], **answers[identifier]}
                if answers[identifier]['answer']:
                    evaluated.append((index, row))
        if evaluated and kind not in phase['selected']:
            index, row = min(evaluated, key=lambda pair: (-pair[1]['evidence_strength'], -pair[1]['evidence_count'], pair[0]))
            phase['selected'][kind] = {**row, 'judgement_id': f'A5.{kind}.{index + 1}'}
    added = []
    exhausted = []
    for kind in DOMAINS:
        if kind in phase['selected']:
            continue
        rows = phase['rankings'][kind]
        start = phase['offsets'][kind]
        stop = min(start + phase['k'], len(rows))
        if start == stop:
            exhausted.append(kind)
        for index in range(start, stop):
            added.append(_definition(phase['templates'], 'A5.connection', f'A5.{kind}.{index + 1}', {
                'self': excerpt(phase['material']['text']), 'signal': excerpt(rows[index]['text'])}))
        phase['offsets'][kind] = stop
    if exhausted:
        state.update(status='BLOCKED', pending=None, blocked={
            'element_id': 'A6.selection', 'attempt': 1,
            'last_failure': [{'check': 'connected_pair_required',
                              'reason': 'No connected signal in: ' + ', '.join(exhausted)}],
            'judgements': deepcopy(phase['judgements'])})
        return
    if not added:
        selected = phase['selected']
        added.append(_definition(phase['templates'], 'A7.central-question', 'A7.central-question', {
            'self': excerpt(phase['material']['text']),
            'art_history': excerpt(selected['art-history']['text']),
            'market': excerpt(selected['marketing']['text']),
            'art_reason': answers[selected['art-history']['judgement_id']]['reason'],
            'market_reason': answers[selected['marketing']['judgement_id']]['reason']}))
    state['sequence']['elements'].extend(added)


def start(engine, signals: list[dict], *, requested_at: str, k=5, workspace_root: Path | None = None, intent: str | None = None) -> dict:
    if engine.path.exists():
        return engine.next()
    sequence = load_sequence(REGISTRY)
    # A5/A7 definitions are templates registered and checked by the same validator.
    templates = {item['element_id']: deepcopy(item) for item in sequence['elements'][1:]}
    sequence['elements'] = [sequence['elements'][0]]
    context = initial_context(signals, engine.directory.parent, engine.run_id, k=k, requested_at=requested_at, intent=intent)
    context['phase_a']['templates'] = templates
    context['phase_a']['operation_template'] = deepcopy(sequence['elements'][0])
    if workspace_root is not None:
        from tools.theme_sources import projections
        context['phase_a']['public_sources'] = projections(context['phase_a']['signals'], workspace_root)
    return engine.next(sequence=sequence, context=context)


def provenance(state: dict) -> dict:
    phase = state['context']['phase_a']
    selected = phase['selected']
    signals = {signal['signal_id']: signal for signal in phase['signals']}
    return {'contract_version': 'phase-a-provenance/v1', 'run_id': state['run_id'],
            'source_repository': state['source_repository'], 'source_commit': state['source_commit'],
            'material': deepcopy(phase['material']), 'material_selection': deepcopy(phase['material_selection']), 'operation': state['answers']['A3.operation'],
            'operations': [value for key, value in state['answers'].items() if key == 'A3.operation' or key.startswith('A3.operation.')],
            'matching_history': deepcopy(phase.get('matching_history', [])),
            'creative_question': state['answers']['A7.central-question'],
            'selected': {kind: {'signal': deepcopy(signals[row['signal_id']]),
                                'matching_text': row['text'], 'public_source_refs': deepcopy(row['public_source_refs']), 'relation_sources': deepcopy(row['relation_sources']),
                                'score': row['score'], 'matched_terms': deepcopy(row.get('matched_terms', [])),
                                'score_breakdown': deepcopy(row.get('score_breakdown', {})),
                                'connection': deepcopy(state['answers'][row['judgement_id']])}
                         for kind, row in selected.items()}}


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
        ids = [('self', origin['material']['signal_id'])] + [(kind, selected[kind]['signal']['signal_id']) for kind in DOMAINS]
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
        origin['reference_aliases'] = reference_aliases(request)
        origin_bytes = canonical(origin)
        origin_uri = f"urn:orchestration:phase-a:{engine.run_id}:sha256:{digest(origin)}"
        request['source']['artifact_uri'] = origin_uri
        request['references'].append({'label': 'phase-a-provenance.json: material, selected signals and connection reasons',
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
