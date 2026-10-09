from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tools.element import Engine
from tools.element_checks import check_value
from tools.theme_elements import start, ranked
from tools.validate import validate_signal
from tests.test_theme_elements import signals, reply, NOW


VOCAB = {'contract_version': 'operation-vocabulary/v1', 'operations': [
    {'id': 'defer', 'label': '決定の先送り', 'definition': '条件が整うまで決定を後に回す。'},
    {'id': 'release-control', 'label': '統制を外す', 'definition': '意識的な主題決定や理性的な統制を外して進める。'}]}


def tagged():
    rows = signals()
    art = rows[1]['domain']['art_history']
    art['operation_vocabulary'] = deepcopy(VOCAB)
    art['operation_tags'] = [{'operation_id': 'defer', 'evidence': '先送りによって時間をずらす作品',
                             'source_locator': art['content'][0]['source_locator'],
                             'source_refs': art['content'][0]['source_refs']}]
    rows[2]['certainty']['basis'] = '決定の先送りで余白を得る観測'
    return rows


class OperationVocabularyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Engine('operation-test', Path(self.temp.name).resolve())

    def answer(self, report, value):
        return self.engine.answer(reply(report['next_action']['request'], value))

    def test_choice_then_separate_exact_evidence_then_matching(self):
        report = start(self.engine, tagged(), requested_at=NOW)
        request = report['next_action']['request']
        self.assertEqual('choice', request['answer_format']['type'])
        report = self.answer(report, 'defer')
        self.assertEqual('A3.evidence.1', report['next_action']['request']['element_id'])
        report = self.answer(report, '素材にない根拠')
        self.assertEqual(2, report['next_action']['request']['attempt'])
        self.assertEqual('defer', report['answers']['A3.operation'])
        report = self.answer(report, '決定を後に回す')
        self.assertEqual('A5.art-history.1', report['next_action']['request']['element_id'])
        self.assertEqual(report, self.engine.next())
        phase = json.loads(self.engine.path.read_text())['context']['phase_a']
        self.assertEqual('operation-tags/v1', phase['rankings']['art-history'][0]['matching_mode'])
        self.assertEqual(['defer'], phase['rankings']['art-history'][0]['matched_terms'])

    def test_unknown_choice_retries_same_element(self):
        report = start(self.engine, tagged(), requested_at=NOW)
        report = self.answer(report, '先送り')
        self.assertEqual(2, report['next_action']['request']['attempt'])
        self.assertEqual({}, report['answers'])

    def test_untagged_candidates_are_ordered_not_dropped(self):
        rows = tagged()
        rows[1]['domain']['art_history']['operation_tags'] = []
        report = start(self.engine, rows, requested_at=NOW)
        report = self.answer(report, 'defer')
        report = self.answer(report, '決定を後に回す')
        request = report['next_action']['request']
        # No tag overlap used to re-ask A3; now the candidate still reaches A5.
        self.assertEqual('A5.art-history.1', request['element_id'])
        self.assertEqual('先送りによって時間をずらす作品', request['inputs']['signal'])
        self.assertEqual('決定を後に回す', report['answers']['A3.evidence.1'])
        self.assertNotIn('A3.operation.2', report['answers'])

    def test_stop_first_blocks_without_empty_evidence_or_a5(self):
        report = start(self.engine, tagged(), requested_at=NOW)
        report = self.answer(report, 'これ以上なし')
        self.assertEqual('BLOCKED', report['status'])
        self.assertEqual(1, report['accepted_count'])

    def test_tag_rank_ignores_accidental_literal_name_and_url_matches(self):
        rows = tagged()
        rows[1]['domain']['art_history']['operation_tags'] = []
        rows[1]['domain']['art_history']['content'][0]['text'] = '決定の先送り defer'
        self.assertEqual(0, ranked('defer', rows, 'art-history')[0]['score'])
        rows[1]['domain']['art_history']['operation_tags'] = tagged()[1]['domain']['art_history']['operation_tags']
        row = ranked('defer', rows, 'art-history')[0]
        self.assertEqual(1, row['score'])
        self.assertEqual('先送りによって時間をずらす作品', row['operation_evidence'][0]['evidence'])

    def test_mixed_vocabularies_are_rejected_before_state(self):
        rows = tagged()
        other = deepcopy(rows[1]); other['signal_id'] = 'other-art'
        other['domain']['art_history']['operation_vocabulary']['operations'].reverse()
        with self.assertRaisesRegex(ValueError, 'MIXED_OPERATION_VOCABULARY'):
            start(self.engine, rows + [other], requested_at=NOW)
        self.assertFalse(self.engine.path.exists())

    def test_unknown_duplicate_and_empty_tags_are_invalid(self):
        for change in ('unknown', 'duplicate', 'empty'):
            row = tagged()[1]
            tags = row['domain']['art_history']['operation_tags']
            if change == 'unknown': tags[0]['operation_id'] = 'unknown'
            elif change == 'duplicate': tags.append(deepcopy(tags[0]))
            else: tags[0]['evidence'] = ' '
            self.assertTrue(validate_signal(row), change)

    def test_input_excerpt_is_literal_not_normalized(self):
        for value in ('a b', 'ＡＢ'):
            self.assertTrue(check_value(value, ['exact_input_excerpt:body'], inputs={'body':'AB'}, ledger={}, previous_answers={}))
        self.assertEqual([], check_value('AB', ['exact_input_excerpt:body'], inputs={'body':'AB'}, ledger={}, previous_answers={}))

    def test_malformed_owner_fields_return_schema_errors_without_crashing(self):
        for change in ('operations-null', 'tags-null', 'id-object', 'evidence-object', 'domain-null'):
            row = tagged()[1]; art = row['domain']['art_history']
            if change == 'operations-null': art['operation_vocabulary']['operations'] = None
            elif change == 'tags-null': art['operation_tags'] = None
            elif change == 'id-object': art['operation_vocabulary']['operations'][0]['id'] = {}
            elif change == 'domain-null': row['domain'] = None
            else: art['operation_tags'][0]['evidence'] = {}
            self.assertTrue(validate_signal(row), change)

    def test_tag_only_owner_signal_retains_sources_without_inventing_content(self):
        from tests.test_adapter_art_history import load_input
        from tools.adapters import adapt_art_history_signal
        record = load_input(); record['relations'] = []
        record['operation_vocabulary'] = deepcopy(VOCAB)
        record['operation_tags'] = [{'operation_id':'defer', 'evidence':'先送りする',
            'source_locator':record['source_locator']+'#lead',
            'source_refs':['https://example.test/tag-source']}]
        signal = adapt_art_history_signal(record)
        self.assertNotIn('content', signal['domain']['art_history'])
        self.assertEqual(record['operation_tags'], signal['domain']['art_history']['operation_tags'])
        self.assertIn('https://example.test/tag-source', [r['locator'] for r in signal['evidence_refs']])
        self.assertEqual([], validate_signal(signal))
