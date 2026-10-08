"""Replay the reviewed run's accepted A3 against the actual owner art export.

Self prose stays on stdin and in disposable Git-external Engine state. The
marketing input is the unchanged synthetic fixture, not the owner's market.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.adapters import adapt_art_history_signal
from tools.element import Engine
from tools.theme_elements import MATCHING_FIELDS, ranked, start
from tools.validate import validate_signal_export

ACTUAL_ACCEPTED_OPERATION = '確定の保留'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', required=True, type=Path)
    parser.add_argument('--operation', choices=[ACTUAL_ACCEPTED_OPERATION], default=ACTUAL_ACCEPTED_OPERATION)
    args = parser.parse_args()
    material = sys.stdin.read().strip()
    if not material:
        raise ValueError('Supply the authorized material on stdin')
    raw = args.export.read_bytes()
    export = json.loads(raw)
    if validate_signal_export(export) or export['source_repository'] != 'art-history':
        raise ValueError('Invalid art-history export')
    records = {r['signal_id']: r for r in export['signals']}
    normalized = []
    for record in export['signals']:
        if record['commit'] != export['source_commit']:
            raise ValueError('Export source commit mismatch')
        normalized.append(adapt_art_history_signal(record))
    fixture = ROOT / 'tests/fixtures/signal'
    self_signal = json.loads((fixture / 'valid_self.json').read_text())
    domain = self_signal['domain']['self_model']
    for key in ('tensions', 'seeks', 'protects', 'avoids', 'traits', 'states', 'contexts', 'recurring_patterns'):
        domain[key] = [material] if key == 'tensions' else []
    market = json.loads((fixture / 'valid_marketing.json').read_text())
    with tempfile.TemporaryDirectory(prefix='issue283-a3-replay-') as directory:
        engine = Engine('issue283-accepted-a3', Path(directory).resolve())
        report = start(engine, [self_signal, market, *normalized], requested_at=market['generated_at'])
        request = report['next_action']['request']
        report = engine.answer({'contract_version': 'element-answer/v1',
                                **{key: request[key] for key in ('run_id', 'element_id', 'attempt')},
                                'value': args.operation})
        state = json.loads(engine.path.read_text())
        if state['answers'].get('A3.operation') != ACTUAL_ACCEPTED_OPERATION:
            raise ValueError('The real accepted operation was not accepted by this Engine replay')
        if report != engine.next():
            raise ValueError('The pending checkpoint did not replay identically')
        phase = state['context']['phase_a']
        rows = ranked([args.operation], phase['signals'], 'art-history')
        next_action = deepcopy(report['next_action'])
        if next_action:
            inputs = next_action['request']['inputs']
            for key in ('material', 'self'):
                if key in inputs:
                    inputs[key] = {'omitted': 'authorized self material',
                                   'sha256': hashlib.sha256(inputs[key].encode()).hexdigest()}
    scores = []
    for row in rows:
        record = records[row['signal_id']]
        scores.append({key: deepcopy(row[key]) for key in MATCHING_FIELDS} | {
            'entity_id': record['entity_id'], 'entity_labels': record.get('entity_labels', []),
            'candidate_kind': 'method' if record.get('method') else 'movement',
            'source_locator': record['source_locator'],
            'content_sha256': hashlib.sha256(row['text'].encode()).hexdigest()})
    positive = sum(row['score'] > 0 for row in rows)
    result = {'scope': 'Actual owner art export and the reviewed run accepted A3; native Engine replay with a synthetic self transport and unchanged synthetic marketing fixture; not full owner-profile Production',
              'material_sha256': hashlib.sha256(material.encode()).hexdigest(),
              'operation_source': 'Actual run accepted A3 answer supplied explicitly in the Issue 283 review',
              'operations': [args.operation], 'additional_operation_answered': False,
              'source_repository': export['source_repository'], 'source_commit': export['source_commit'],
              'export_sha256': hashlib.sha256(raw).hexdigest(), 'export_count': len(records),
              'content_count': sum(bool(r.get('content')) for r in records.values()),
              'excluded_signal_ids': [s['signal_id'] for s in phase['excluded_signals'] if s['signal_id'] in records],
              'eligible_count': len(rows), 'positive_score_count': positive,
              'below_minimum_count': sum(row['match_status'] == 'BELOW_MINIMUM_CONTENT_MATCH' for row in rows),
              'zero_score_count': len(rows) - positive,
              'candidate_kinds': dict(Counter(row['candidate_kind'] for row in scores)),
              'status': phase['matching_history'][-1]['diagnostics']['art-history']['reason'] or 'MATCHED',
              'synthetic_harness_requested_at': market['generated_at'],
              'engine_status': report['status'], 'accepted_count': report['accepted_count'],
              'matching_history': phase['matching_history'],
              'next_action': next_action, 'request_material_redacted': True,
              'a5_judgements_created': bool(phase['judgements']),
              'top_five': [row for row in scores if row['score'] > 0][:5],
              'diagnostic_top_five': scores[:5], 'scores': scores}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    # WAITING is an observed successful retry checkpoint, not a matching success.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
