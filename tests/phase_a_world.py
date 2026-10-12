"""A synthetic Phase A world: self records, art/market signals with cards, and the blobs they quote."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from tools.element import canonical

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/signal'
NOW = '2026-10-10T00:00:00+09:00'
COMMITS = {'art-history': 'a' * 40, 'marketing-trends': 'b' * 40}
STATEMENT = '概念と表現の対応が自分の中で言語化できていない間は、費用の確定を先に進めることを避ける可能性がある'


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def self_signal(index=0, statement=None, field='tensions', condition=None):
    signal = fixture('valid_self.json')
    signal['signal_id'] = f'self:derived-{index:03d}'
    signal['source']['entity_ids'] = [f'self-entity-{index:03d}']
    signal['evidence_refs'][0]['entity_id'] = f'self-entity-{index:03d}'
    model = signal['domain']['self_model']
    for name in ('seeks', 'protects', 'avoids', 'tensions', 'recurring_patterns', 'traits', 'states', 'contexts'):
        model[name] = []
    model[field] = [statement or f'{STATEMENT}（{index}）']
    if condition:
        model['contexts'] = [condition]
    return signal


def _blob(kind, index):
    marker = f'tag{kind[0]}{index}'
    excerpt = f'{marker}は制作過程の記録として自発的に構成を決める実践'
    raw = f'---\nid: {kind}-{index}\n---\n# 定義\n{excerpt}である。\n'.encode()
    return excerpt, raw


def art_signal(index, blobs, *, card=True):
    signal = fixture('valid_art_history.json')
    signal['signal_id'] = f'art-history:a{index:02d}'
    signal['source'].update(commit=COMMITS['art-history'], entity_ids=[f'art-entity-{index:03d}'],
                            locators=[f'knowledge/a{index:02d}.md'])
    signal['evidence_refs'][0]['entity_id'] = f'art-entity-{index:03d}'
    domain = signal['domain']['art_history']
    domain['label_ja'] = f'美術{index}'
    domain['time'], domain['geo'] = '1950年代', '北米'
    if card:
        excerpt, raw = _blob('art', index)
        path = f'knowledge/a{index:02d}.md'
        blobs[('art-history', path)] = raw
        domain['card'] = [{'text': excerpt, 'source_locator': path + '#定義', 'source_sha256': hashlib.sha256(raw).hexdigest()}]
    return signal


def market_signal(index, blobs, *, expires='2027-01-01T00:00:00+09:00', card=True):
    signal = fixture('valid_marketing.json')
    signal['signal_id'] = f'marketing:m{index:02d}'
    signal['source'].update(commit=COMMITS['marketing-trends'], entity_ids=[f'trend-entity-{index:03d}'],
                            locators=[f'trends/m{index:02d}.md'])
    signal['evidence_refs'][0]['entity_id'] = f'trend-entity-{index:03d}'
    signal['freshness']['revalidate_at'] = '2027-02-01T00:00:00+09:00'
    domain = signal['domain']['marketing']
    domain.update(stage='growing', expires_at=expires, revalidate_at=signal['freshness']['revalidate_at'])
    domain['label_ja'] = f'市場{index}'
    if card:
        excerpt = f'tagm{index}は制作過程の記録として自発的に構成を決める実践'
        raw = f'---\nid: market-{index}\n---\n# 題\n\n## 足元の根拠（完了した事実）\n\n**{excerpt}**である。\n'.encode()
        path = f'trends/m{index:02d}.md'
        blobs[('marketing-trends', path)] = raw
        domain['card'] = [{'text': excerpt, 'source_locator': path + '#足元の根拠', 'source_sha256': hashlib.sha256(raw).hexdigest()}]
    return signal


def world(art=10, market=4, selfs=1):
    blobs = {}
    signals = [self_signal(i) for i in range(selfs)]
    signals += [art_signal(i, blobs) for i in range(art)] + [market_signal(i, blobs) for i in range(market)]
    return signals, blobs


def blob_source(blobs):
    def read(repository, commit, path):
        assert commit == COMMITS[repository]
        return blobs[(repository, path)]
    return read


def reply(request, value, kind='fake'):
    return {'contract_version': 'element-answer/v1', 'answerer_kind': kind,
            **{key: request[key] for key in ('run_id', 'element_id', 'attempt')}, 'value': value}


class Policy:
    """A scripted answerer that reads the request like an LLM would and returns plausible values."""

    def __init__(self, engine, *, screen=None, rank=None, link='逆', probe=None, overrides=None):
        self.engine, self.screen, self.rank, self.link = engine, screen, rank, link
        self.probe, self.overrides = probe, overrides or {}
        self.requests = []

    def answers(self):
        return self.engine.status()['answers']

    def value(self, request):
        identifier, inputs = request['element_id'], request['inputs']
        if identifier in self.overrides:
            override = self.overrides[identifier]
            return override(request) if callable(override) else override
        if '.screen.' in identifier:
            return self.screen(request) if self.screen else '1'
        if '.rank.' in identifier:
            return self.rank(request) if self.rank else '1'
        if identifier.endswith('.type'):
            return self.link
        answers = self.answers()
        if identifier.endswith('.card-quote'):
            return inputs['card_excerpts'].split(' / ')[0][:25]
        if identifier.endswith('.self-quote'):
            return inputs['material_statement'][:18]
        if identifier.endswith('.sentence'):
            return f"{inputs['self_quote']}間は確定を避けるが、{inputs['card_quote']}ので{inputs['link_type']}になる"
        if identifier.endswith('.probe'):
            return self.probe(request) if self.probe else self.link
        if identifier == 'A7.overlap':
            quotes = [answers[f'A5.{kind}.{self.k(kind)}.{part}'] for kind, part in
                      (('art', 'self-quote'), ('art', 'card-quote'), ('market', 'card-quote'))]
            label = f"{inputs['art_label']}では、" if 'art_label' in inputs else ''  # required by contains_terms:art_label
            return f'{label}{quotes[0]}間と、{quotes[1]}ことと、{quotes[2]}ことは、決める時をどこに置くかで向き合っている'
        if identifier == 'A7.question':
            label = f"{inputs['art_label']}で、" if 'art_label' in inputs else ''
            return f"{label}{inputs['self_quote']}間と{inputs['art_card_quote']}と{inputs['market_card_quote']}は、どのように向き合えるか？"
        raise AssertionError(identifier)

    def k(self, kind):
        return max(int(re.match(rf'A5\.{kind}\.(\d+)\.', key).group(1)) for key in self.answers() if key.startswith(f'A5.{kind}.'))

    def drive(self, report, limit=400):
        while report['next_action'] and limit:
            limit -= 1
            request = report['next_action']['request']
            self.requests.append(canonical(request))
            report = self.engine.answer(reply(request, self.value(request)))
        assert limit, 'run did not terminate'
        return report
