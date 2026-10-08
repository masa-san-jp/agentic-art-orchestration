"""Read-only A3/A4 acceptance probe; retain scores, never the supplied self prose."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.adapters import adapt_art_history_signal
from tools.element_checks import check_value
from tools.theme_elements import ranked
from tools.validate import validate_signal_export


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', required=True, type=Path)
    parser.add_argument('--operation', required=True, action='append')
    args = parser.parse_args()
    material = sys.stdin.read().strip()
    if not material:
        raise ValueError('Supply the authorized material on stdin')
    previous = {}
    for i, operation in enumerate(args.operation):
        if not 2 <= len(operation) <= 20 or check_value(operation,
            ['non_empty', 'not_similar_to:material', 'not_similar:0.8', 'forbidden:無し,未記入,∩'],
            inputs={'material': material}, ledger={}, previous_answers=previous):
            raise ValueError('Operation does not pass the A3 checks')
        previous[str(i)] = operation
    raw = args.export.read_bytes()
    export = json.loads(raw)
    if validate_signal_export(export) or export['source_repository'] != 'art-history':
        raise ValueError('Invalid art-history export')
    records = {r['signal_id']: r for r in export['signals']}
    normalized = []
    excluded = []
    for record in export['signals']:
        if record['commit'] != export['source_commit']:
            raise ValueError('Export source commit mismatch')
        signal = adapt_art_history_signal(record)
        domain = signal['domain']['art_history']
        if signal['freshness']['status'] == 'current' and (
            signal['validity']['status'] == 'valid' or
            signal['validity']['status'] == 'unknown' and (domain.get('content') or domain.get('method'))):
            normalized.append(signal)
        else:
            excluded.append(signal['signal_id'])
    rows = ranked(args.operation, normalized, 'art-history')
    scores = []
    for row in rows:
        record = records[row['signal_id']]
        scores.append({key: deepcopy(row[key]) for key in
                       ('signal_id', 'score', 'matched_terms', 'score_breakdown')} | {
            'entity_id': record['entity_id'], 'entity_labels': record.get('entity_labels', []),
            'candidate_kind': 'method' if record.get('method') else 'movement',
            'source_locator': record['source_locator'],
            'content_sha256': hashlib.sha256(row['text'].encode()).hexdigest()})
    positive = sum(row['score'] > 0 for row in rows)
    result = {'scope': 'Supplied authorized material and actual owner export; A3/A4 probe, not a full Production run',
              'material_sha256': hashlib.sha256(material.encode()).hexdigest(),
              'operation_source': 'Agent-authored from the supplied material', 'operations': args.operation,
              'source_repository': export['source_repository'], 'source_commit': export['source_commit'],
              'export_sha256': hashlib.sha256(raw).hexdigest(), 'export_count': len(records),
              'content_count': sum(bool(r.get('content')) for r in records.values()),
              'excluded_signal_ids': excluded, 'eligible_count': len(rows),
              'positive_score_count': positive, 'zero_score_count': len(rows) - positive,
              'candidate_kinds': dict(Counter(row['candidate_kind'] for row in scores)),
              'status': 'MATCHED' if positive else 'NO_CONTENT_TERM_OVERLAP',
              'id_order_top_five': sorted(row['signal_id'] for row in rows)[:5],
              'top_five': scores[:5] if positive else [], 'scores': scores}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if positive else 1


if __name__ == '__main__':
    raise SystemExit(main())
