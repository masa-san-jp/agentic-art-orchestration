from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from tools.element import Engine, canonical
from tools.element_answerer import FakeAnswerer
from tools.theme_elements import initial_context, materials, ranked, signal_body, start, write_request

ROOT = Path(__file__).resolve().parents[1]
NOW = '2026-08-15T00:00:00+09:00'


def signals():
    rows = [json.loads((ROOT / 'tests/fixtures/signal' / name).read_text()) for name in
            ('valid_self.json', 'valid_art_history.json', 'valid_marketing.json')]
    rows[0]['domain']['self_model'].update(seeks=[], protects=[], avoids=[], traits=[], states=[], contexts=[],
                                         recurring_patterns=[], tensions=['決定を後に回す'])
    rows[1]['statement'] = '時間をずらす作品'
    rows[2]['statement'] = '余白を求める動き'
    rows[2]['certainty']['basis'] = '時間をかけて選択したいという観測'
    return rows


def reply(request, value):
    return {'contract_version': 'element-answer/v1',
            **{key: request[key] for key in ('run_id', 'element_id', 'attempt')}, 'value': value}


class ThemeElementsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.engine = Engine('phase-test', self.root)

    def open(self, rows=None, k=5):
        return start(self.engine, rows or signals(), requested_at=NOW, k=k)

    def answer(self, report, value):
        return self.engine.answer(reply(report['next_action']['request'], value))

    def finish(self):
        fake = FakeAnswerer({'A3.operation': ['先送り'],
            'A5.art-history.1': [{'answer': True, 'reason': '決定を後に回すことで時間をずらす。'}],
            'A5.marketing.1': [{'answer': True, 'reason': '決定を後に回すことが余白を生む。'}],
            'A7.central-question': ['決定を後に回すと、時間のずれは選択の余白になるか？']})
        report = self.open()
        while report['next_action']:
            report = self.engine.answer(fake.answer(report['next_action']['request']))
        self.assertEqual('COMPLETED', report['status'])
        return report

    def test_source_term_check_requires_declared_source_keys(self):
        from tools.element_contracts import load_sequence, validate_sequence
        sequence = load_sequence()
        sequence['elements'][0]['checks'] = ['contains_source_terms:material,missing']
        self.assertTrue(validate_sequence(sequence))

    def test_all_exported_content_fields_are_individual_materials(self):
        rows = signals()
        domain = rows[0]['domain']['self_model']
        for key in ('tensions', 'recurring_patterns', 'seeks', 'avoids', 'protects', 'traits', 'states', 'contexts'):
            domain[key] = [key + ' one', key + ' two', ' ']
        self.assertEqual(16, len(materials(rows)))
        self.assertEqual(set(domain) - {'consent_scope', 'export_permitted', 'raw_voice_locator'},
                         {item['attribute'] for item in materials(rows)})
        self.assertNotIn('raw_voice_locator', canonical(materials(rows)))

    def test_optional_intent_ranks_unused_material_without_retaining_raw_input(self):
        from tools.candidate_selection import intent_sha256
        rows = signals()
        rows[0]['domain']['self_model']['tensions'] = ['余白を保つ', '決定を後に回す']
        intent = '  決定    を後に  回す  '
        context = initial_context(rows, self.root, 'intent', requested_at=NOW, intent=intent)
        self.assertEqual('決定を後に回す', context['phase_a']['material']['text'])
        self.assertEqual(intent_sha256(intent), context['phase_a']['material_selection']['intent_sha256'])
        self.assertNotIn(intent, canonical(context))
        with self.assertRaises(ValueError):
            initial_context(rows, self.root, 'invalid-intent', requested_at=NOW, intent='   ')

    def test_material_order_is_independent_of_export_order_and_empty_items(self):
        rows = signals()
        rows[0]['domain']['self_model']['tensions'] = ['second', 'first', '', 'first']
        self.assertEqual(2, len(materials(rows)))
        self.assertEqual(materials(rows), materials(list(reversed(rows))))

    def test_completed_runs_prefer_unused_material_and_reject_repeated_operation(self):
        self.finish()
        rows = signals()
        rows[0]['domain']['self_model']['tensions'].append('別の合成素材')
        other = Engine('second', self.root)
        report = start(other, rows, requested_at=NOW)
        self.assertEqual('別の合成素材', report['next_action']['request']['inputs']['material'])
        report = other.answer(reply(report['next_action']['request'], '先送り'))
        self.assertEqual(2, report['next_action']['request']['attempt'])
        self.assertIn('not_similar:0.8', [f['check'] for f in report['next_action']['request']['previous_failure']])

    def test_matching_reads_full_methods_relations_and_market_basis(self):
        rows = signals()
        rows[1]['domain']['art_history']['method'] = {'fixes': ['先送り'], 'varies': ['待機'], 'requires': ['準備']}
        rows[1]['domain']['art_history']['relations'][0]['target_entity_id'] = '未来'
        self.assertIn('準備', signal_body(rows[1]))
        self.assertIn('未来', signal_body(rows[1]))
        self.assertGreater(ranked('先送り', rows, 'art-history')[0]['score'], 0)
        self.assertGreater(ranked('選択', rows, 'marketing')[0]['score'], 0)

    def test_equal_match_scores_use_signal_id_not_hash(self):
        rows = signals()
        clone = deepcopy(rows[1])
        clone['signal_id'] += '-b'
        rows.append(clone)
        ranked_rows = ranked('先送り', rows, 'art-history')
        self.assertEqual(sorted(row['signal_id'] for row in ranked_rows), [row['signal_id'] for row in ranked_rows])

    def test_later_definitions_are_frozen_in_the_same_run(self):
        report = self.open()
        with patch('tools.theme_elements.REGISTRY', self.root / 'missing-registry.yaml'):
            report = self.answer(report, '先送り')
            report = self.answer(report, {'answer': True, 'reason': '決定を後に回すことが時間をずらす。'})
            report = self.answer(report, {'answer': True, 'reason': '決定を後に回すことが余白を生む。'})
        self.assertEqual('A7.central-question', report['next_action']['request']['element_id'])

    def test_a3_empty_and_long_values_retry_only_one_element(self):
        report = self.open()
        for bad in (' ', 'あ' * 21):
            report = self.answer(report, bad)
            self.assertEqual('A3.operation', report['next_action']['request']['element_id'])
        self.assertEqual(report, start(Engine('phase-test', self.root), [], requested_at=NOW))

    def test_a5_reason_requires_terms_from_both_sources_and_one_sentence(self):
        report = self.answer(self.open(), '先送り')
        for reason in ('時間をずらす。', '決定を後に回す。', '決定と時間。別の理由。'):
            report = self.answer(report, {'answer': True, 'reason': reason})
            self.assertEqual('A5.art-history.1', report['next_action']['request']['element_id'])
        self.assertEqual(1, report['accepted_count'])

    def test_expand_next_window_without_rechecking_already_accepted_pairs(self):
        rows = signals()
        second = deepcopy(rows[1])
        second['signal_id'] += '-second'
        rows.append(second)
        report = self.answer(self.open(rows, k=1), '先送り')
        report = self.answer(report, {'answer': False, 'reason': '決定と時間は直接にはつながらない。'})
        report = self.answer(report, {'answer': True, 'reason': '決定を後に回すことで余白ができる。'})
        self.assertEqual('A5.art-history.2', report['next_action']['request']['element_id'])
        self.assertEqual(report, self.engine.next())
        report = self.answer(report, {'answer': True, 'reason': '決定を後に回すことで時間がずれる。'})
        self.assertEqual('A7.central-question', report['next_action']['request']['element_id'])
        state = json.loads(self.engine.path.read_text())
        self.assertEqual(3, len(state['context']['phase_a']['judgements']))
        self.assertFalse(state['answers']['A5.art-history.1']['answer'])

    def test_one_domain_exhausted_blocks_with_all_reasons_and_selected_other(self):
        report = self.answer(self.open(), '先送り')
        report = self.answer(report, {'answer': False, 'reason': '決定と時間は直接にはつながらない。'})
        report = self.answer(report, {'answer': True, 'reason': '決定を後に回すことで余白ができる。'})
        self.assertEqual('BLOCKED', report['status'])
        self.assertEqual('A6.selection', report['blocked']['element_id'])
        self.assertIn('art-history', report['blocked']['last_failure'][0]['reason'])
        self.assertEqual(2, len(report['blocked']['judgements']))
        self.assertEqual(report, self.engine.next())

    def test_select_evidence_stronger_yes_within_window(self):
        rows = signals()
        second = deepcopy(rows[1])
        second['signal_id'] += '-second'
        second['evidence_refs'].append({**second['evidence_refs'][0], 'locator': 'synthetic/distinct-evidence'})
        rows.append(second)
        report = self.answer(self.open(rows), '先送り')
        while report['next_action']['request']['element_id'].startswith('A5.'):
            request = report['next_action']['request']
            word = '時間' if 'art-history' in request['element_id'] else '余白'
            report = self.answer(report, {'answer': True, 'reason': f'決定を後に回すことで{word}が変わる。'})
        selected = json.loads(self.engine.path.read_text())['context']['phase_a']['selected']
        self.assertEqual(second['signal_id'], selected['art-history']['signal_id'])

    def test_a7_requires_three_sources_question_form_limit_and_forbidden_checks(self):
        report = self.answer(self.open(), '先送り')
        for reason in ('決定を後に回すことで時間をずらす。', '決定を後に回すことで余白が生まれる。'):
            report = self.answer(report, {'answer': True, 'reason': reason})
        for value in ('決定を後に回すと作品になるか？', '決定と時間と余白。', '決定∩時間∩余白か？', '決定時間余白' + '長' * 120 + '？'):
            report = self.answer(report, value)
            self.assertEqual('A7.central-question', report['next_action']['request']['element_id'])
        report = self.answer(report, '決定を後に回すと、時間のずれは選択の余白になるか？')
        self.assertEqual('COMPLETED', report['status'])

    def test_rr_question_is_inferred_and_provenance_is_structured_create_only(self):
        report = self.finish()
        output = self.root / 'requests'
        path = write_request(self.engine, output, slug='synthetic', title='合成テーマ', research_root=None)
        request = yaml.safe_load(path.read_text())
        self.assertEqual(report['answers']['A7.central-question'], request['intent']['creative_question'])
        self.assertNotIn('∩', request['intent']['creative_question'])
        origin = json.loads((output / 'phase-a-provenance.json').read_text())
        self.assertEqual('決定を後に回す', origin['material']['text'])
        self.assertEqual({'art-history', 'marketing'}, set(origin['selected']))
        self.assertTrue(all(row['connection']['answer'] for row in origin['selected'].values()))
        self.assertIn(request['source']['artifact_uri'], [ref['uri'] for ref in request['references']])
        self.assertEqual('PRIVATE_DERIVED', request['data_boundary']['classification'])
        self.assertFalse(request['data_boundary']['raw_data_included'])
        before = path.read_bytes()
        self.assertEqual(path, write_request(self.engine, output, slug='synthetic', title='合成テーマ', research_root=None))
        self.assertEqual(before, path.read_bytes())
        path.write_text('tampered')
        with self.assertRaises(ValueError):
            write_request(self.engine, output, slug='synthetic', title='合成テーマ', research_root=None)

    def test_real_public_ark_uri_has_a_reversible_opaque_reference(self):
        from tools.theme_elements import reference_aliases
        uri = 'https://example.invalid/ark:/synthetic-source'
        reference = {'label': 'synthetic-source', 'uri': uri, 'rights_status': 'UNKNOWN'}
        request = {'references': [deepcopy(reference)]}
        aliases = reference_aliases(request)
        self.assertEqual(uri, aliases[0]['uri'])
        self.assertEqual('UNKNOWN', request['references'][0]['rights_status'])
        self.assertEqual(aliases[0]['request_uri'], request['references'][0]['uri'])
        self.assertTrue(request['references'][0]['uri'].startswith('urn:orchestration:phase-a-reference:sha256:'))
        for unsafe in (uri + '?token=synthetic', uri + '#synthetic'):
            request = {'references': [{**reference, 'uri': unsafe}]}
            self.assertEqual([], reference_aliases(request))
            self.assertEqual(unsafe, request['references'][0]['uri'])
        for unsafe in ('https://user:pass@example.invalid/ark:/synthetic',
                       'https://example.invalid/ark:/PRIVATE_RAW'):
            with self.assertRaisesRegex(ValueError, 'UNSAFE_PUBLIC_REFERENCE_ALIAS'):
                reference_aliases({'references': [{**reference, 'uri': unsafe}]})

    def test_invalid_export_diagnostics_do_not_disclose_rejected_values(self):
        rows = signals()
        rows[0]['domain']['self_model']['tensions'] = {'PRIVATE_REJECTED_EXPORT': 'PRIVATE_REJECTED_EXPORT'}
        with self.assertRaises(ValueError) as error:
            initial_context(rows, self.root, 'invalid', requested_at=NOW)
        self.assertIn('INVALID_NORMALIZED_SIGNAL', str(error.exception))
        self.assertNotIn('PRIVATE_REJECTED_EXPORT', str(error.exception))

    def test_stale_denied_empty_missing_duplicate_inputs_never_get_a_theme(self):
        for mutate in ('stale', 'denied', 'empty', 'missing', 'duplicate', 'expired'):
            rows = signals()
            if mutate == 'stale': rows[2]['freshness']['status'] = 'stale'
            if mutate == 'denied': rows[0]['domain']['self_model']['export_permitted'] = False
            if mutate == 'empty': rows[0]['domain']['self_model']['tensions'] = []
            if mutate == 'missing': rows = rows[:-1]
            if mutate == 'duplicate': rows.append(deepcopy(rows[1]))
            if mutate == 'expired': rows[2]['domain']['marketing']['expires_at'] = '2026-08-01T00:00:00+09:00'
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                initial_context(rows, self.root, 'invalid', requested_at=NOW)

    def test_same_run_freezes_export_and_cli_answer_uses_common_engine(self):
        report = self.open()
        before = self.engine.request_bytes()
        changed = signals()
        changed[0]['domain']['self_model']['tensions'] = ['later export']
        self.assertEqual(report, start(self.engine, changed, requested_at=NOW))
        self.assertEqual(before, self.engine.request_bytes())
        result = subprocess.run([sys.executable, 'tools/element.py', 'answer', '--run-id', 'phase-test',
                                 '--state-root', str(self.root)], input=canonical(reply(report['next_action']['request'], '先送り')),
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('A5.art-history.1', json.loads(result.stdout)['next_action']['request']['element_id'])

    def test_resumed_run_allocates_after_external_native_research_requests(self):
        from tools.run import run
        self.finish()
        accepted = self.root / 'research-work/projects/earlier/00_intake/research-request.yaml'
        accepted.parent.mkdir(parents=True)
        accepted.write_text('request_id: RR091\n')
        def child(root, arguments, python, **kwargs):
            return {'status': 'NOT_READY' if arguments[0] == 'tools/complete.py' else 'APPLIED'}
        with patch('tools.run._prepare_runtime_workspace', return_value=({'status': 'PASSED'}, self.root)), \
             patch('tools.run._run_tool') as tool, patch('tools.run._run_child', side_effect=child):
            report = run('PRIVATE_RESUME_INTENT', self.root, self.root, 'phase-test', 'artistic-research', None, None, NOW,
                         sys.executable, profile_root=self.root / 'synthetic-profile',
                         research_root=self.root / 'research-code', production_root=self.root / 'production-code',
                         research_work_root=self.root / 'research-work')
        self.assertEqual('RESEARCH_PENDING', report['status'])
        self.assertEqual('ELEMENT_INFERRED', report['theme_proposal']['mode'])
        self.assertTrue((self.root / 'phase-test/requests/RR092.yaml').is_file())
        self.assertNotIn('PRIVATE_RESUME_INTENT', (self.root / 'phase-test/run.json').read_text())
        tool.assert_not_called()

    def test_run_live_default_returns_element_and_omits_legacy_candidate_steps(self):
        from tools.run import run
        def ingest(args, python):
            output = Path(args[args.index('--output') + 1])
            output.mkdir(parents=True, exist_ok=True)
            for row in signals():
                directory = output / row['signal_kind']
                directory.mkdir(exist_ok=True)
                (directory / 'signal.json').write_text(canonical(row))
            return {'status': 'PASSED'}
        with patch('tools.run._prepare_runtime_workspace', return_value=({'status': 'PASSED'}, self.root)), \
             patch('tools.run._run_tool', side_effect=ingest) as tool, \
             patch('tools.theme_sources.projections', return_value={'evidence': {}, 'targets': {}}):
            report = run('決定 PRIVATE_OPTIONAL_INTENT', self.root, self.root, 'default', 'artistic-research', None, None, NOW,
                         sys.executable, profile_root=self.root / 'synthetic-profile',
                         research_root=self.root / 'research-code', production_root=self.root / 'production-code')
            self.assertEqual('element', report['next_action']['kind'])
            self.assertEqual('A3.operation', report['next_action']['request']['element_id'])
            self.assertEqual(1, tool.call_count)
            self.assertFalse({'candidates', 'gates', 'selection'} & {step['step'] for step in report['steps']})
            saved = json.loads((self.root / 'default/run.json').read_text())
            self.assertNotIn('next_action', saved)
            self.assertNotIn('決定を後に回す', canonical(saved))
            self.assertNotIn('PRIVATE_OPTIONAL_INTENT', canonical(saved))
            self.assertNotIn('--intent', report['resume_command'])


class ThemeUncertaintyTests(unittest.TestCase):
    def test_native_self_unknown_freshness_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = signals()
            rows[0]['freshness']['status'] = 'unknown'
            context = initial_context(rows, Path(directory).resolve(), 'native-self', requested_at=NOW)
            self.assertEqual('unknown', context['phase_a']['signals'][0]['freshness']['status'])

    def test_sourced_draft_method_is_retained_without_validity_promotion(self):
        from tools.adapters import adapt_art_history_signal
        record = json.loads((ROOT / 'tests/fixtures/signal/method_adapter_input.json').read_text())
        method = adapt_art_history_signal(record)
        with tempfile.TemporaryDirectory() as directory:
            rows = signals()
            rows[1] = method
            context = initial_context(rows, Path(directory).resolve(), 'draft', requested_at=NOW)
            self.assertEqual('unknown', context['phase_a']['signals'][1]['validity']['status'])
            rows[1]['freshness']['status'] = 'stale'
            with self.assertRaises(ValueError):
                initial_context(rows, Path(directory).resolve(), 'stale', requested_at=NOW)

    def test_a3_cannot_copy_material_verbatim(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine('copy', Path(directory).resolve())
            report = start(engine, signals(), requested_at=NOW)
            report = engine.answer(reply(report['next_action']['request'], '決定を後に回す'))
            self.assertIn('not_similar_to:material', [f['check'] for f in report['next_action']['request']['previous_failure']])



class ThemeRequestBudgetTests(unittest.TestCase):
    def test_long_material_is_retained_but_each_request_stays_small(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = signals()
            full = '決定を後に回す場面' * 1000
            rows[0]['domain']['self_model']['tensions'] = [full]
            engine = Engine('budget', Path(directory).resolve())
            report = start(engine, rows, requested_at=NOW)
            request = report['next_action']['request']
            self.assertLess(len(canonical(request['inputs']).encode()), 4096)
            state = json.loads(engine.path.read_text())
            self.assertEqual(full, state['context']['phase_a']['material']['text'])
            report = engine.answer(reply(request, '保留'))
            while report.get('next_action') and report['next_action']['request']['element_id'].startswith('A5.'):
                request = report['next_action']['request']
                self.assertLess(len(canonical(request['inputs']).encode()), 4096)
                word = '時間' if 'art-history' in request['element_id'] else '余白'
                report = engine.answer(reply(request, {'answer': True, 'reason': f'決定を後に回すことが{word}につながる。'}))
            self.assertEqual('A7.central-question', report['next_action']['request']['element_id'])
            self.assertLess(len(canonical(report['next_action']['request']['inputs']).encode()), 4096)




class ShortSourceTermsTests(unittest.TestCase):
    def test_single_character_content_word_and_short_latin_word_are_anchors(self):
        from tools.element_checks import source_terms
        self.assertIn('手', source_terms('手'))
        self.assertIn('go', source_terms('go'))
        self.assertNotIn('する', source_terms('する'))
        self.assertEqual(set(), source_terms('a an of to in as is it on at by or I'))
        from tools.element_checks import check_value
        self.assertEqual([], check_value('手は動く。', ['contains_source_terms:source'], inputs={'source': '手'}, ledger={}, previous_answers={}))


if __name__ == '__main__':
    unittest.main()
