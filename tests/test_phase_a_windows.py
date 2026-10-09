from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from tools.element import Engine
from tools.theme_elements import best_case_inferences, ranked, start, windowing_config, WINDOWING
from tests.test_operation_relations import candidate, rows
from tests.test_theme_elements import NOW, reply

ART_YES = {'answer': True, 'reason': '決定を後に回すことで時間をずらす。'}
ART_NO = {'answer': False, 'reason': '決定と時間は直接にはつながらない。'}
MARKET_YES = {'answer': True, 'reason': '決定を後に回すことが余白を生む。'}


def source(extra):
    """Three owner-tagged art candidates (same / complement / contrast) plus untagged ones."""
    result = rows()
    original = result[1]
    for name, ids in extra:
        row = candidate(original, name, ids, '先送りによって時間をずらす作品')
        for ref in row['evidence_refs']:
            if 'entity_id' in ref:
                ref['entity_id'] = 'movement/' + name
        result.append(row)
    return result


class PhaseAWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Engine('window-test', Path(self.temp.name).resolve())

    def answer(self, report, value):
        return self.engine.answer(reply(report['next_action']['request'], value))

    def to_a5(self, signals, **options):
        report = start(self.engine, signals, requested_at=NOW, **options)
        report = self.answer(report, 'defer')
        return self.answer(report, '決定を後に回す')

    def test_tags_only_order_candidates_and_every_candidate_is_listed(self):
        extra = [('z-untagged', []), ('a-untagged', []), ('contrast', ['decide-in-action']),
                 ('complement', ['impose-constraints']), ('same', ['defer'])]
        result = ranked('defer', source(extra), 'art-history')
        names = [row['entity_id'].split('/')[-1] for row in result]
        # The fixture's own tagged signal is "same"; untagged ones follow in a fixed order.
        self.assertEqual(['same', 'complement', 'contrast'], [n for n in names if n in ('same', 'complement', 'contrast')])
        self.assertEqual(names[:-2], [n for n in names if n not in ('a-untagged', 'z-untagged')])
        self.assertEqual(['a-untagged', 'z-untagged'], names[-2:])
        self.assertEqual(len(extra) + 1, len(result))

    def test_window_without_yes_advances_only_that_domain_and_keeps_judgements(self):
        signals = source([('b', ['impose-constraints']), ('c', ['decide-in-action'])])
        report = self.to_a5(signals, k=2)
        ids = []
        while report['next_action'] and report['next_action']['request']['element_id'].startswith('A5.'):
            request = report['next_action']['request']
            ids.append(request['element_id'])
            if request['element_id'] == 'A5.marketing.1':
                report = self.answer(report, MARKET_YES)
            elif len(ids) < 3 and request['element_id'].startswith('A5.art-history'):
                report = self.answer(report, ART_NO)
            else:
                report = self.answer(report, ART_YES)
        self.assertEqual(['A5.art-history.1', 'A5.art-history.2', 'A5.marketing.1', 'A5.art-history.3'], ids)
        self.assertEqual('A7.central-question', report['next_action']['request']['element_id'])
        phase = json.loads(self.engine.path.read_text())['context']['phase_a']
        self.assertEqual(4, len(phase['judgements']))
        self.assertFalse(phase['judgements']['A5.art-history.1']['answer'])
        self.assertEqual('A5.art-history.3', phase['selected']['art-history']['judgement_id'])

    def test_all_candidates_judged_no_blocks_with_the_observed_cause(self):
        signals = source([('b', ['impose-constraints'])])
        report = self.to_a5(signals, k=2)
        report = self.answer(report, ART_NO)
        report = self.answer(report, ART_NO)
        report = self.answer(report, MARKET_YES)
        self.assertEqual('BLOCKED', report['status'])
        reason = report['blocked']['last_failure'][0]['reason']
        self.assertIn('art-history', reason)
        self.assertNotIn('marketing', reason)
        self.assertNotIn('No remaining operation', reason)
        self.assertEqual({'candidates': 2, 'with_text': 2, 'without_text': 0, 'judged': 2, 'yes': 0, 'windows_used': 1},
                         report['blocked']['domains']['art-history'])
        self.assertIn('候補2件', reason)
        self.assertIn('「はい」0件', reason)

    def test_candidates_without_text_are_counted_not_judged(self):
        signals = source([('empty', [])])
        empty = signals[-1]['domain']['art_history']
        empty.pop('content')
        empty['operation_tags'] = []
        report = self.to_a5(signals, k=5)
        self.assertEqual('A5.art-history.1', report['next_action']['request']['element_id'])
        phase = json.loads(self.engine.path.read_text())['context']['phase_a']
        self.assertEqual({'candidates': 2, 'with_text': 1}, phase['candidate_counts']['art-history'])

    def test_market_without_literal_overlap_is_still_judged(self):
        signals = source([])
        signals[2]['statement'] = '全く別の話題'
        signals[2]['certainty']['basis'] = '関係のない観測'
        report = self.to_a5(signals, k=5)
        report = self.answer(report, ART_YES)
        request = report['next_action']['request']
        self.assertEqual('A5.marketing.1', request['element_id'])
        report = self.answer(report, {'answer': False, 'reason': '決定を後に回すことと全く別の話題は結びつかない。'})
        self.assertEqual('BLOCKED', report['status'])
        self.assertIn('marketing', report['blocked']['last_failure'][0]['reason'])

    def test_inference_cap_blocks_with_reason_instead_of_asking_more(self):
        signals = source([('b', ['impose-constraints']), ('c', ['decide-in-action'])])
        cap = best_case_inferences(1)
        report = self.to_a5(signals, k=1, max_inferences=cap)
        report = self.answer(report, ART_NO)
        report = self.answer(report, MARKET_YES)
        self.assertEqual('BLOCKED', report['status'])
        failure = report['blocked']['last_failure'][0]
        self.assertEqual('inference_budget', failure['check'])
        self.assertIn(f'上限({cap})', failure['reason'])
        self.assertIn('art-history', failure['reason'])
        self.assertEqual(cap - 1, len(json.loads(self.engine.path.read_text())['history']))

    def test_retries_count_toward_the_cap(self):
        cap = best_case_inferences(1)
        report = start(self.engine, source([]), requested_at=NOW, k=1, max_inferences=cap)
        for _ in range(cap):
            if report['status'] != 'WAITING':
                break
            report = self.answer(report, '先送り')
        self.assertEqual('BLOCKED', report['status'])
        self.assertEqual(cap, len(json.loads(self.engine.path.read_text())['history']))
        self.assertEqual('inference_budget', report['blocked']['last_failure'][-1]['check'])

    def test_cap_below_best_case_is_rejected_before_state(self):
        with self.assertRaisesRegex(ValueError, 'best case'):
            start(self.engine, source([]), requested_at=NOW, k=5, max_inferences=best_case_inferences(5) - 1)
        self.assertFalse(self.engine.path.exists())

    def test_default_config_is_valid_and_bad_values_fail(self):
        config = windowing_config()
        self.assertTrue(5 <= config['window_size'] <= 10)
        self.assertGreaterEqual(config['max_inferences'], best_case_inferences(config['window_size']))
        raw = yaml.safe_load(WINDOWING.read_text())
        for change in ({'window_size': 4}, {'window_size': 11}, {'max_inferences': best_case_inferences(5) - 1},
                       {'window_size': True}, {'version': 2}):
            path = Path(self.temp.name) / 'bad.yaml'
            path.write_text(yaml.safe_dump({**deepcopy(raw), **change}))
            with self.assertRaises(ValueError, msg=str(change)):
                windowing_config(path)


if __name__ == '__main__':
    unittest.main()
