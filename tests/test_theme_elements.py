from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import tempfile
import unittest

import yaml

from tests.phase_a_world import NOW, Policy, STATEMENT, art_signal, blob_source, market_signal, reply, self_signal, world
from tools.card_sources import PhaseABlocked
from tools.element import Engine, canonical
from tools.theme_elements import budget_cap, initial_context, materials, rank_matches, start, write_request

ROOT = Path(__file__).resolve().parents[1]


class PhaseATestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def engine(self, run_id='phase-test', root=None):
        return Engine(run_id, root or self.root)

    def open(self, signals, blobs, run_id='phase-test', root=None, **options):
        engine = self.engine(run_id, root)
        options.setdefault('requested_at', NOW)
        return engine, start(engine, signals, blob_source=blob_source(blobs), **options)

    def state(self, engine):
        return json.loads(engine.path.read_text(encoding='utf-8'))

    def run_to_end(self, signals, blobs, run_id='phase-test', root=None, policy=None, **options):
        engine, report = self.open(signals, blobs, run_id, root, **options)
        policy = policy or Policy(engine)
        policy.engine = engine
        return engine, policy, policy.drive(report)

    def stop(self, signals, blobs, **options):
        with self.assertRaises(PhaseABlocked) as caught:
            self.open(signals, blobs, **options)
        return caught.exception


class FullRunTests(PhaseATestCase):
    def test_every_eligible_card_is_screened_and_the_run_completes(self):
        signals, blobs = world(art=10, market=4)
        engine, policy, report = self.run_to_end(signals, blobs)
        self.assertEqual('COMPLETED', report['status'])
        state = self.state(engine)
        phase = state['context']['phase_a']
        for kind, count in (('art', 10), ('market', 4)):
            screened = [identifier for number, window in enumerate(phase['windows'][kind], 1)
                        for identifier in window if f'A4.{kind}.screen.{number:02d}' in state['answers']]
            self.assertEqual(count, len(screened))
            self.assertEqual(sorted(phase['order'][kind]), sorted(screened))
        self.assertEqual([8, 2], [len(window) for window in phase['windows']['art']])
        self.assertLessEqual(len(state['history']), phase['budget']['cap'])
        self.assertEqual({'art', 'market'}, set(phase['adopted']))
        self.assertTrue(all(len(request.encode()) <= 4096 for request in policy.requests))

    def test_central_question_satisfies_the_design_checks(self):
        signals, blobs = world()
        engine, _, report = self.run_to_end(signals, blobs)
        question = report['answers']['A7.question']
        self.assertLessEqual(len(question), 120)
        self.assertTrue(question.endswith('？'))
        self.assertIn('どのように', question)
        for key in ('A7.overlap', 'A7.question'):
            self.assertIn(key, report['answers'])

    def test_adopted_quotes_are_verbatim_in_card_material_and_pinned_blob(self):
        signals, blobs = world()
        engine, _, report = self.run_to_end(signals, blobs)
        state = self.state(engine)
        phase = state['context']['phase_a']
        for kind in ('art', 'market'):
            k = phase['adopted_k'][kind]
            card = phase['cards'][phase['adopted'][kind]]
            quote = state['answers'][f'A5.{kind}.{k}.card-quote']
            self.assertTrue(any(quote in excerpt for excerpt in card['excerpts']))
            for source in card['sources']:
                raw = blobs[(source['repository'], source['locator'].split('#')[0])]
                self.assertEqual(hashlib.sha256(raw).hexdigest(), source['blob_sha256'])
                self.assertIn(card['excerpts'][0], raw.decode())
            self.assertIn(state['answers'][f'A5.{kind}.{k}.self-quote'], phase['material']['statement'])

    def test_replaying_recorded_answers_reproduces_requests_and_output_byte_for_byte(self):
        signals, blobs = world()
        first_engine, first, report = self.run_to_end(signals, blobs, root=self.root / 'a')
        second_engine, second, again = self.run_to_end(signals, blobs, root=self.root / 'b')
        self.assertEqual(first.requests, second.requests)
        self.assertEqual(canonical(report), canonical(again))
        from tools.theme_elements import provenance
        self.assertEqual(canonical(provenance(self.state(first_engine))), canonical(provenance(self.state(second_engine))))

    def test_stopping_anywhere_and_resuming_returns_the_same_next_request(self):
        signals, blobs = world(art=10, market=3)
        _, reference, _ = self.run_to_end(signals, blobs, root=self.root / 'ref')
        engine, report = self.open(signals, blobs, root=self.root / 'cut')
        for index, expected in enumerate(reference.requests):
            self.assertEqual(expected, canonical(report['next_action']['request']), index)
            self.assertEqual(expected.encode(), self.engine('phase-test', self.root / 'cut').request_bytes())
            report = engine.answer(reply(report['next_action']['request'], Policy(engine).value(report['next_action']['request'])))
            engine = self.engine('phase-test', self.root / 'cut')

    def test_card_order_does_not_depend_on_input_order(self):
        signals, blobs = world(art=12, market=4)
        shuffled = deepcopy(signals)
        random.Random(7).shuffle(shuffled)
        _, left = self.open(signals, blobs, root=self.root / 'l')
        _, right = self.open(shuffled, blobs, root=self.root / 'r')
        self.assertEqual(left['next_action']['request'], right['next_action']['request'])

    def test_hidden_values_and_private_fields_never_reach_the_answerer_or_the_stored_trace(self):
        signals, blobs = world()
        signals[0]['domain']['self_model']['raw_voice_locator'] = 'self-model/approved-locator/PRIVATE-VOICE'
        engine, policy, _ = self.run_to_end(signals, blobs)
        joined = '\n'.join(policy.requests)
        for hidden in ('"expected"', '"specificity"', '"label"'):
            self.assertNotIn(hidden, joined)
        self.assertNotIn('PRIVATE-VOICE', engine.path.read_text())
        from tools.theme_elements import provenance
        self.assertNotIn('raw_voice_locator', canonical(provenance(self.state(engine))))
        probes = [json.loads(text) for text in policy.requests if '.probe' in text]
        self.assertTrue(probes and all(request['answer_context'] == 'fresh' for request in probes))
        self.assertTrue(all(request['inputs']['sentence_masked'].count('＿＿') >= 1 for request in probes))

    def test_screen_picks_are_recorded_as_a_position_distribution(self):
        signals, blobs = world()
        engine, _, _ = self.run_to_end(signals, blobs)
        from tools.theme_elements import provenance
        distribution = provenance(self.state(engine))['position_distribution']
        self.assertEqual(3, sum(distribution.values()))
        self.assertEqual({'1'}, set(distribution))

    def test_code_keeps_no_literal_score_or_operation_relation_selection(self):
        text = (ROOT / 'tools/theme_elements.py').read_text()
        for removed in ('content_matches', 'matching_terms', 'matching_words', 'matching_diagnostic', 'tag_matches',
                        'operation_relations', 'operation_vocabulary', 'A3.operation', 'prior_operations', 'intent_score'):
            self.assertNotIn(removed, text)


class RealDataShapeTests(PhaseATestCase):
    """The scale of the first real run: 179 art entries (23 windows), 65 market trends (9 windows)."""

    def test_windows_cap_and_a_sparse_run_match_the_design_numbers(self):
        signals, blobs = world(art=179, market=65)
        picks = lambda request: '1' if int(request['element_id'].rsplit('.', 1)[1]) % 3 == 0 else '0'
        engine, policy, report = self.run_to_end(signals, blobs, policy=Policy(self.engine(), screen=picks))
        phase = self.state(engine)['context']['phase_a']
        self.assertEqual((23, 9), (len(phase['windows']['art']), len(phase['windows']['market'])))
        self.assertEqual(120, phase['budget']['cap'])
        self.assertEqual('COMPLETED', report['status'])
        self.assertLessEqual(len(self.state(engine)['history']), 120)
        self.assertTrue(all(len(request.encode()) <= 4096 for request in policy.requests))

    def test_the_window_order_is_reproducible_from_the_recorded_seed_rule(self):
        signals, blobs = world(art=40, market=10)
        engine, _ = self.open(signals, blobs)
        phase = self.state(engine)['context']['phase_a']
        material, use_count = phase['material']['signal_id'], phase['material_selection']['use_count']
        for kind in ('art', 'market'):
            expected = sorted(phase['order'][kind], key=lambda identifier: hashlib.sha256(
                f'{material}:{use_count}:{identifier}'.encode()).hexdigest())
            self.assertEqual(expected, phase['order'][kind])
            self.assertEqual(phase['order'][kind], [identifier for window in phase['windows'][kind] for identifier in window])
            self.assertNotEqual(sorted(phase['order'][kind]), phase['order'][kind])

    def test_all_zero_answers_on_the_real_shape_stop_with_the_counts(self):
        signals, blobs = world(art=179, market=65)
        _, _, report = self.run_to_end(signals, blobs, policy=Policy(self.engine(), screen=lambda r: '0'))
        self.assertEqual({'reason': 'NO_PICK:art', 'windows': 23, 'cards': 179}, report['blocked'])


class MaterialTests(PhaseATestCase):
    def test_one_self_signal_is_one_material_and_a_condition_is_not_a_material(self):
        signal = self_signal(0, condition='研究の打ち合わせの場面')
        rows = materials([signal])
        self.assertEqual(1, len(rows))
        self.assertEqual('本人の素材（引っ張り合っていること）：' + STATEMENT + '（0）\n条件：研究の打ち合わせの場面', rows[0]['text'])
        self.assertEqual(STATEMENT + '（0）', rows[0]['statement'])

    def test_consent_gate_and_empty_export(self):
        denied = self_signal(0)
        denied['domain']['self_model']['export_permitted'] = False
        with self.assertRaisesRegex(PhaseABlocked, 'SELF_EXPORT_NOT_PERMITTED'):
            materials([denied])
        signals, blobs = world(selfs=0)
        self.assertEqual('SELF_MODEL_EMPTY', self.stop(signals, blobs).reason)
        empty = self_signal(0)
        empty['domain']['self_model']['tensions'] = []
        signals, blobs = world(selfs=0)
        self.assertEqual('SELF_MODEL_EMPTY', self.stop([empty, *signals], blobs).reason)

    def test_owner_pin_and_missing_pin(self):
        signals, blobs = world(selfs=3)
        engine, report = self.open(signals, blobs, self_signal='self:derived-002')
        phase = self.state(engine)['context']['phase_a']
        self.assertEqual('self:derived-002', phase['material']['signal_id'])
        self.assertEqual('owner-pinned', phase['material_selection']['rule'])
        stop = self.stop(signals, blobs, self_signal='self:nope', run_id='other')
        self.assertEqual(('SELF_SIGNAL_NOT_FOUND', 'self:nope'), (stop.reason, stop.details['signal_id']))

    def test_n_records_are_each_used_once_in_n_consecutive_runs(self):
        signals, blobs = world(art=12, market=8, selfs=4)
        used = []
        for number in range(4):
            engine, _, report = self.run_to_end(signals, blobs, run_id=f'rotate-{number}',
                                                requested_at=f'2026-10-1{number}T00:00:00+09:00')
            self.assertEqual('COMPLETED', report['status'])
            used.append(self.state(engine)['context']['phase_a']['material']['signal_id'])
        self.assertEqual(sorted(f'self:derived-{i:03d}' for i in range(4)), sorted(used))

    def test_equal_use_prefers_the_less_used_field(self):
        signals, blobs = world(art=12, market=8, selfs=0)
        signals += [self_signal(0, field='tensions'), self_signal(1, field='seeks'), self_signal(2, field='seeks')]
        order = []
        for number in range(3):
            engine, _, _ = self.run_to_end(signals, blobs, run_id=f'group-{number}', requested_at=f'2026-10-1{number}T00:00:00+09:00')
            order.append(self.state(engine)['context']['phase_a']['material']['field'])
        self.assertEqual(2, order.count('seeks'))
        self.assertNotEqual(order[0], order[1])

    def test_recently_adopted_cards_are_excluded_per_domain_for_three_runs(self):
        signals, blobs = world(art=12, market=8, selfs=1)
        adopted = []
        for number in range(3):
            engine, _, _ = self.run_to_end(signals, blobs, run_id=f'recent-{number}', requested_at=f'2026-10-1{number}T00:00:00+09:00')
            adopted.append(self.state(engine)['context']['phase_a']['adopted'])
        engine, _ = self.open(signals, blobs, run_id='recent-3', requested_at='2026-10-13T00:00:00+09:00')
        exclusion = self.state(engine)['context']['phase_a']['exclusions']
        self.assertEqual(sorted(row['art'] for row in adopted), exclusion['art']['recently_adopted_ids'])
        self.assertEqual(3, exclusion['art']['excluded']['recently_adopted'])
        self.assertEqual(9, exclusion['art']['eligible'])


class CandidateStopTests(PhaseATestCase):
    def test_expired_market_names_the_real_cause(self):
        signals, blobs = world(market=0)
        signals += [market_signal(i, blobs, expires='2026-10-09T00:00:00+09:00') for i in range(5)]
        stop = self.stop(signals, blobs)
        self.assertEqual(('MARKET_NO_ELIGIBLE_CARDS', {'expired': 5}), (stop.reason, stop.details['excluded']))

    def test_art_without_cards_and_the_exclusion_breakdown(self):
        signals, blobs = world(art=0)
        signals += [art_signal(i, blobs, card=False) for i in range(3)]
        stop = self.stop(signals, blobs)
        self.assertEqual(('ART_NO_ELIGIBLE_CARDS', {'no_card_text': 3}), (stop.reason, stop.details['excluded']))

    def test_exclusion_counts_are_recorded_in_the_run(self):
        signals, blobs = world(art=3)
        signals += [art_signal(i, blobs, card=False) for i in range(10, 12)]
        signals += [market_signal(i, blobs, expires='2026-10-09T00:00:00+09:00') for i in range(10, 12)]
        engine, _ = self.open(signals, blobs)
        exclusions = self.state(engine)['context']['phase_a']['exclusions']
        self.assertEqual({'eligible': 3, 'excluded': {'no_card_text': 2}, 'recently_adopted_ids': []}, exclusions['art'])
        self.assertEqual({'expired': 2}, exclusions['market']['excluded'])

    def test_card_that_is_not_in_the_pinned_blob_blocks_instead_of_being_dropped(self):
        signals, blobs = world()
        key = next(key for key in blobs if key[0] == 'art-history')
        blobs[key] = blobs[key].replace('制作過程'.encode(), '別の過程'.encode())
        stop = self.stop(signals, blobs)
        self.assertEqual('CARD_SOURCE_MISMATCH', stop.reason)
        self.assertEqual('blob sha256 differs', stop.details['detail'])

    def test_exported_hash_must_match_and_a_missing_checkout_is_not_ignored(self):
        signals, blobs = world()
        art = next(signal for signal in signals if signal['signal_kind'] == 'art-history')
        path = art['domain']['art_history']['card'][0]['source_locator'].split('#')[0]
        blobs[('art-history', path)] += b'x'
        self.assertEqual('CARD_SOURCE_MISMATCH', self.stop(signals, blobs).reason)
        signals, _ = world()
        with self.assertRaises(PhaseABlocked) as caught:
            initial_context(signals, self.root, 'no-checkout', requested_at=NOW)
        self.assertEqual('CARD_SOURCE_MISMATCH', caught.exception.reason)

    def test_a_request_that_cannot_fit_is_reported_with_its_element(self):
        signals, blobs = world()
        signals[0]['domain']['self_model']['tensions'] = ['長い' * 2200]
        stop = self.stop(signals, blobs)
        self.assertEqual(('REQUEST_TOO_LARGE', 'A4.art.screen.01'), (stop.reason, stop.details['element_id']))

    def test_oversized_windows_are_split_but_every_card_is_still_seen(self):
        signals, blobs = world(art=8, market=3)
        signals[0]['domain']['self_model']['tensions'] = ['長い' * 500]
        engine, _ = self.open(signals, blobs)
        windows = self.state(engine)['context']['phase_a']['windows']['art']
        self.assertGreater(len(windows), 1)
        self.assertEqual(8, sum(len(window) for window in windows))


class StopReasonTests(PhaseATestCase):
    def test_every_window_answered_zero_stops_with_no_pick_and_counts_the_material(self):
        signals, blobs = world(art=10, market=4, selfs=2)
        engine, _, report = self.run_to_end(signals, blobs, policy=Policy(Engine('phase-test', self.root), screen=lambda r: '0'))
        self.assertEqual('BLOCKED', report['status'])
        self.assertEqual({'reason': 'NO_PICK:art', 'windows': 2, 'cards': 10}, report['blocked'])
        first = self.state(Engine('phase-test', self.root))['context']['phase_a']['material']['signal_id']
        engine, _, report = self.run_to_end(signals, blobs, run_id='second', requested_at='2026-10-11T00:00:00+09:00')
        self.assertNotEqual(first, self.state(engine)['context']['phase_a']['material']['signal_id'])

    def test_market_with_no_pick_stops_after_art_is_adopted(self):
        signals, blobs = world()
        engine = self.engine()
        policy = Policy(engine, screen=lambda r: '0' if r['element_id'].startswith('A4.market') else '1')
        _, _, report = self.run_to_end(signals, blobs, policy=policy)
        self.assertEqual('NO_PICK:market', report['blocked']['reason'])
        self.assertIn('A5.art.1.sentence.probe', report['answers'])

    def test_all_finalists_none_stops_with_no_confirmed_link(self):
        signals, blobs = world(art=12, market=4)
        _, _, report = self.run_to_end(signals, blobs, policy=Policy(self.engine(), link='なし'), window_size=2)
        blocked = report['blocked']
        self.assertEqual('NO_CONFIRMED_LINK:art', blocked['reason'])
        self.assertEqual(5, len(blocked['finalists']))
        self.assertEqual({'なし'}, {row['answer'] for row in blocked['finalists']})
        self.assertEqual(5, len({row['card_id'] for row in blocked['finalists']}))

    def test_fewer_picks_than_finalist_slots_also_end_as_no_confirmed_link(self):
        signals, blobs = world(art=3, market=3)
        _, _, report = self.run_to_end(signals, blobs, policy=Policy(self.engine(), link='なし'), window_size=1)
        self.assertEqual('NO_CONFIRMED_LINK:art', report['blocked']['reason'])
        self.assertEqual(3, len(report['blocked']['finalists']))

    def test_replaced_winner_replays_only_its_group_and_the_final(self):
        signals, blobs = world(art=12, market=3)
        engine = self.engine()
        policy = Policy(engine, link='逆', overrides={'A5.art.1.type': 'なし'})
        _, _, report = self.run_to_end(signals, blobs, policy=policy, window_size=1)
        ids = [key for key in report['answers'] if key.startswith('A4.art.rank.')]
        self.assertEqual(['A4.art.rank.1.1', 'A4.art.rank.1.1.v2', 'A4.art.rank.1.2', 'A4.art.rank.2.1', 'A4.art.rank.2.1.v2'], sorted(ids))
        self.assertEqual('COMPLETED', report['status'])

    def test_an_element_that_keeps_failing_stops_with_its_id_and_last_check(self):
        signals, blobs = world()
        policy = Policy(self.engine(), overrides={'A5.art.1.card-quote': '文中にない引用ですがこれは長い'})
        _, _, report = self.run_to_end(signals, blobs, policy=policy)
        self.assertEqual('ELEMENT_ATTEMPTS_EXHAUSTED', report['blocked']['reason'])
        self.assertEqual('A5.art.1.card-quote', report['blocked']['element_id'])
        self.assertIn('exact_input_excerpt:card_excerpts', [row['check'] for row in report['blocked']['last_failure']])

    def test_the_run_budget_stops_with_a_breakdown(self):
        signals, blobs = world()
        engine, report = self.open(signals, blobs, budget=5)
        policy = Policy(engine)
        report = policy.drive(report)
        blocked = report['blocked']
        self.assertEqual('RUN_BUDGET_EXHAUSTED', blocked['reason'])
        self.assertEqual((5, 5), (blocked['cap'], blocked['used']))
        self.assertEqual(5, sum(blocked['breakdown'].values()))
        self.assertEqual({'A4.art.screen': 2, 'A4.art.rank': 1, 'A5.art': 2}, blocked['breakdown'])

    def test_finishing_exactly_at_the_cap_is_not_a_budget_stop(self):
        signals, blobs = world(art=2, market=2)
        engine, report = self.open(signals, blobs, root=self.root / 'free')
        total = len(Policy(engine).drive(report)['answers'])
        engine, _, report = self.run_to_end(signals, blobs, root=self.root / 'exact', budget=total)
        self.assertEqual('COMPLETED', report['status'])
        _, _, report = self.run_to_end(signals, blobs, root=self.root / 'short', budget=total - 1)
        self.assertEqual('RUN_BUDGET_EXHAUSTED', report['blocked']['reason'])

    def test_default_cap_matches_the_design_for_the_real_data_shape(self):
        windows = {'art': [[0]] * 23, 'market': [[0]] * 9}
        self.assertEqual((120, {'screens': 32, 'rank': 7, 'winner_replacements': 16, 'verification': 18, 'a7': 2, 'retry_slack': 45}),
                         budget_cap(windows, 5))
        self.assertEqual([0, 1, 1, 3, 4], [rank_matches(n) for n in (1, 2, 8, 9, 23)])


class VerificationTests(PhaseATestCase):
    def test_a_sentence_read_as_another_kind_is_rewritten_with_a_cumulative_attempt(self):
        signals, blobs = world()
        engine, report = self.open(signals, blobs)
        readings = iter(['同じ', '逆'])
        policy = Policy(engine, probe=lambda request: next(readings) if request['element_id'].startswith('A5.art') else '逆')
        seen = []
        while report['next_action']:
            request = report['next_action']['request']
            if request['element_id'] in ('A5.art.1.sentence', 'A5.art.1.sentence.probe'):
                seen.append((request['element_id'], request['attempt'], request['previous_failure']))
            report = engine.answer(reply(request, policy.value(request)))
        self.assertEqual('COMPLETED', report['status'])
        self.assertEqual([('A5.art.1.sentence', 1, None), ('A5.art.1.sentence.probe', 1, None)], seen[:2])
        self.assertEqual(('A5.art.1.sentence', 2), seen[2][:2])
        self.assertEqual('link_type_probe', seen[2][2][0]['check'])
        self.assertIn('『逆』の関係として読めませんでした', seen[2][2][0]['reason'])
        self.assertEqual(('A5.art.1.sentence.probe', 2), seen[3][:2])
        trials = self.state(engine)['context']['phase_a']['trials']['art.1']
        self.assertEqual([{'probe_answer': '同じ', 'expected': '逆'}], [{k: row[k] for k in ('probe_answer', 'expected')} for row in trials])

    def test_five_misread_sentences_stop_on_the_sentence_element(self):
        signals, blobs = world()
        _, _, report = self.run_to_end(signals, blobs, policy=Policy(self.engine(), probe=lambda r: '背景'))
        self.assertEqual('ELEMENT_ATTEMPTS_EXHAUSTED', report['blocked']['reason'])
        self.assertEqual('A5.art.1.sentence', report['blocked']['element_id'])
        self.assertEqual('link_type_probe', report['blocked']['last_failure'][0]['check'])

    def test_a_sentence_any_card_could_have_is_rejected_for_specificity(self):
        signals, blobs = world()
        engine, report = self.open(signals, blobs)
        policy = Policy(engine, overrides={'A5.art.1.sentence': lambda request: f"{request['self_quote'] if False else request['inputs']['self_quote']}間は確定を避けるが、そこは逆になる"})
        while report['next_action'] and report['next_action']['request']['element_id'] != 'A5.art.1.sentence':
            request = report['next_action']['request']
            report = engine.answer(reply(request, policy.value(request)))
        request = report['next_action']['request']
        report = engine.answer(reply(request, policy.value(request)))
        failed = report['next_action']['request']
        self.assertEqual(('A5.art.1.sentence', 2), (failed['element_id'], failed['attempt']))
        self.assertIn('specific_to_window:specificity', [row['check'] for row in failed['previous_failure']])
        self.assertIn('contains_source_terms:self_quote,card_quote', [row['check'] for row in failed['previous_failure']])

    def test_quoting_only_the_name_is_rejected(self):
        signals, blobs = world()
        engine, report = self.open(signals, blobs)
        policy = Policy(engine)
        while report['next_action']['request']['element_id'] != 'A5.art.1.card-quote':
            request = report['next_action']['request']
            report = engine.answer(reply(request, policy.value(request)))
        request = report['next_action']['request']
        self.assertNotIn('美術', canonical(request['inputs']))
        label = self.state(engine)['context']['phase_a']['cards'][self.state(engine)['context']['phase_a']['finalists']['art']['1']]['label']
        report = engine.answer(reply(request, 'tagの'))
        self.assertIn('exact_input_excerpt:card_excerpts', [row['check'] for row in report['next_action']['request']['previous_failure']])
        self.assertTrue(label.startswith('美術'))


class RequestTests(PhaseATestCase):
    def test_write_request_references_hashed_provenance_and_the_overlap_candidate(self):
        signals, blobs = world()
        engine, _, report = self.run_to_end(signals, blobs)
        output = self.root / 'requests'
        path = write_request(engine, output, slug='phase-a-test', title='Phase A test', research_root=None)
        request = yaml.safe_load(path.read_text())
        origin = json.loads((output / 'phase-a-provenance.json').read_text())
        self.assertEqual(report['answers']['A7.question'], request['intent']['creative_question'])
        self.assertIn(report['answers']['A7.overlap'], request['intent']['purpose'])
        self.assertEqual('phase-a-provenance/v2', origin['contract_version'])
        self.assertTrue(request['source']['artifact_uri'].startswith(f'urn:orchestration:phase-a:{engine.run_id}:sha256:'))
        self.assertEqual(report['answers']['A7.question'], origin['creative_question'])
        self.assertEqual(path, write_request(engine, output, slug='phase-a-test', title='Phase A test', research_root=None))
        for key in ('material', 'cards', 'screens', 'rank', 'verification', 'adopted', 'not_adopted', 'inference',
                    'exclusions', 'position_distribution', 'picked_not_finalist'):
            self.assertIn(key, origin)
        self.assertEqual(['fake'], origin['inference']['answerers'])

    def test_provenance_requires_a_completed_run(self):
        signals, blobs = world()
        engine, _ = self.open(signals, blobs)
        with self.assertRaisesRegex(ValueError, 'not completed'):
            write_request(engine, self.root / 'requests', slug='x-y', title='x', research_root=None)

    def test_real_public_ark_uri_has_a_reversible_opaque_reference(self):
        from tools.theme_elements import reference_aliases
        uri = 'https://n2t.net/ark:/12148/btv1b8449691v'
        request = {'references': [{'label': 'ark', 'uri': uri, 'rights_status': 'UNKNOWN'},
                                  {'label': 'plain', 'uri': 'https://example.test/a', 'rights_status': 'UNKNOWN'}]}
        aliases = reference_aliases(request)
        self.assertEqual(1, len(aliases))
        self.assertEqual(uri, aliases[0]['uri'])
        self.assertTrue(request['references'][0]['uri'].startswith('urn:orchestration:phase-a-reference:sha256:'))

    def test_invalid_signals_and_duplicates_are_rejected_without_echoing_values(self):
        signals, blobs = world()
        broken = deepcopy(signals[1])
        broken['statement'] = ''
        with self.assertRaisesRegex(ValueError, r'INVALID_NORMALIZED_SIGNAL: \d+ validation errors') as caught:
            self.open([broken, *signals], blobs)
        self.assertNotIn('statement', str(caught.exception))
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_SIGNAL_ID'):
            self.open([*signals, deepcopy(signals[1])], blobs, run_id='dup')

    def test_the_same_run_keeps_its_frozen_inputs(self):
        signals, blobs = world()
        engine, first = self.open(signals, blobs)
        changed = deepcopy(signals)
        changed[0]['domain']['self_model']['tensions'] = ['別の記録']
        again = start(engine, changed, requested_at=NOW, blob_source=blob_source(blobs))
        self.assertEqual(first['next_action'], again['next_action'])


if __name__ == '__main__':
    unittest.main()
