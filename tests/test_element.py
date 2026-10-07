from __future__ import annotations

from copy import deepcopy
from decimal import localcontext
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.element import Engine, build_inputs, canonical
from tools.element_answerer import FakeAnswerer, LocalAnswerer
from tools.element_checks import check_value, parse_check, too_similar, valid_url
from tools.element_contracts import load_sequence, validate_contracts, validate_message, validate_sequence

ROOT = Path(__file__).resolve().parents[1]


def single(*, fmt=None, checks=None, inputs=None, attempts=5):
    return {'contract_version': 'element-sequence/v1', 'max_attempts': attempts, 'elements': [{
        'kind': 'element', 'element_id': 'unit.value', 'instruction': '一つの値を返してください。',
        'inputs': inputs or {}, 'answer_format': fmt or {'type': 'text', 'max_chars': 120},
        'checks': checks or []}]}


def answer(request, value):
    kind = request['contract_version'].split('-')[0]
    return {'contract_version': f'{kind}-answer/v1',
            **{key: request[key] for key in ('run_id', 'element_id', 'attempt')},
            'results' if kind == 'search' else 'value': value}


class ElementEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.engine = Engine('fixture', self.root)

    def request(self, report):
        self.assertEqual('element', report['next_action']['kind'])
        return report['next_action']['request']

    def test_demo_fake_end_to_end_and_replay_each_request(self):
        fake = FakeAnswerer()
        report = self.engine.next()
        for index in range(3):
            request = self.request(report)
            saved_bytes = self.engine.request_bytes()
            resumed = Engine('fixture', self.root)
            self.assertEqual(saved_bytes, resumed.request_bytes())
            self.assertEqual(report, resumed.next())
            report = resumed.answer(fake.answer(request))
            self.assertEqual(index + 1, report['accepted_count'])
        self.assertEqual('COMPLETED', report['status'])
        self.assertIsNone(report['next_action'])
        self.assertEqual(report, Engine('fixture', self.root).next())
        self.assertEqual(report, self.engine.answer(fake.answer(request)))

    def test_fake_retries_only_failed_element_and_preserves_answer(self):
        fake = FakeAnswerer({'demo.operation': ['先送り'], 'demo.question': ['', '先送りを変えられるか？'], 'demo.category': ['時間']})
        report = self.engine.next()
        report = self.engine.answer(fake.answer(self.request(report)))
        before = deepcopy(report['answers'])
        report = self.engine.answer(fake.answer(self.request(report)))
        retry = self.request(report)
        self.assertEqual('demo.question', retry['element_id'])
        self.assertEqual(2, retry['attempt'])
        self.assertIn('non_empty', [f['check'] for f in retry['previous_failure']])
        self.assertEqual(before, report['answers'])
        self.assertEqual(canonical(report), canonical(Engine('fixture', self.root).next()))
        report = self.engine.answer(fake.answer(retry))
        next_request = self.request(report)
        self.assertEqual(1, next_request['attempt'])
        self.assertIsNone(next_request['previous_failure'])
        report = self.engine.answer(fake.answer(next_request))
        self.assertEqual('COMPLETED', report['status'])

    def test_default_five_attempts_block_and_persist_last_checks(self):
        fake = FakeAnswerer({'unit.value': ['']})
        report = self.engine.next(sequence=single())
        for attempt in range(1, 6):
            request = self.request(report)
            self.assertEqual(attempt, request['attempt'])
            report = self.engine.answer(fake.answer(request))
        self.assertEqual('BLOCKED', report['status'])
        self.assertEqual('unit.value', report['blocked']['element_id'])
        self.assertIn('non_empty', [f['check'] for f in report['blocked']['last_failure']])
        self.assertEqual(0, report['accepted_count'])
        self.assertEqual(report, Engine('fixture', self.root).status())
        self.assertIsNone(self.engine.request_bytes())

    def test_limit_is_configurable(self):
        report = self.engine.next(sequence=single(attempts=1))
        report = self.engine.answer(answer(self.request(report), ' '))
        self.assertEqual('BLOCKED', report['status'])
        self.assertEqual(1, report['blocked']['attempt'])

    def test_omitted_limit_defaults_to_five(self):
        sequence = single()
        del sequence['max_attempts']
        report = self.engine.next(sequence=sequence)
        self.assertEqual(report, self.engine.next(sequence=sequence))
        for _ in range(5):
            report = self.engine.answer(answer(self.request(report), ' '))
        self.assertEqual('BLOCKED', report['status'])
        self.assertEqual(5, report['blocked']['attempt'])

    def test_identity_schema_and_stale_answers_never_advance(self):
        report = self.engine.next()
        request = self.request(report)
        original = self.engine.path.read_bytes()
        for field, value in [('run_id', 'other'), ('element_id', 'other'), ('attempt', 2), ('contract_version', 'element-answer/v2')]:
            wrong = answer(request, '先送り')
            wrong[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.engine.answer(wrong)
            self.assertEqual(original, self.engine.path.read_bytes())
        good = answer(request, '先送り')
        self.engine.answer(good)
        with self.assertRaises(ValueError):
            self.engine.answer({**good, 'value': '別の操作'})

    def test_saved_answer_replay_returns_current_report_without_mutating_state(self):
        accepted = answer(self.request(self.engine.next()), '先送り')
        report = self.engine.answer(accepted)
        failed = answer(self.request(report), '')
        report = self.engine.answer(failed)
        self.assertEqual(2, self.request(report)['attempt'])
        cases = [('accepted', self.engine, accepted, report, 0),
                 ('failed', self.engine, failed, report, 0)]
        for name, value, exit_code in [('blocked', '', 2), ('completed', '答え', 0)]:
            engine = Engine(name, self.root)
            saved = answer(self.request(engine.next(sequence=single(attempts=1))), value)
            cases.append((name, engine, saved, engine.answer(saved), exit_code))
        search_engine = Engine('search-replay', self.root)
        sequence = single()
        sequence['elements'].insert(0, {'kind': 'search', 'element_id': 'lookup',
                                        'query': {'literal': '時間'}, 'limit': 1})
        saved_search = answer(self.request(search_engine.next(sequence=sequence)), [
            {'url': 'https://example.invalid/source', 'title': '資料', 'body': '時間の記録。'}])
        cases.append(('search', search_engine, saved_search, search_engine.answer(saved_search), 0))
        for name, engine, saved, expected, exit_code in cases:
            with self.subTest(name=name):
                checkpoint = engine.path.read_bytes()
                command = [sys.executable, 'tools/element.py', 'answer', '--run-id', engine.run_id,
                           '--state-root', str(self.root)]
                replay = subprocess.run(command, cwd=ROOT, input=canonical(saved),
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(exit_code, replay.returncode, replay.stderr)
                self.assertEqual(expected, json.loads(replay.stdout))
                self.assertEqual(checkpoint, engine.path.read_bytes())
                changed = deepcopy(saved)
                if 'results' in changed:
                    changed['results'][0]['title'] = '別の資料'
                else:
                    changed['value'] = '別の答え'
                rejected = subprocess.run(command, cwd=ROOT, input=canonical(changed),
                                          capture_output=True, text=True, timeout=30)
                self.assertEqual(1, rejected.returncode)
                self.assertEqual(checkpoint, engine.path.read_bytes())

    def test_format_failures_retry_instead_of_accepting(self):
        cases = [({'type': 'text', 'max_chars': 2}, '長すぎる'),
                 ({'type': 'choice', 'choices': ['時間', '空間']}, '別'),
                 ({'type': 'boolean_with_reason', 'max_chars': 5}, {'answer': False, 'reason': ' '}),
                 ({'type': 'boolean_with_reason', 'max_chars': 5}, 'はい'),
                 ({'type': 'text', 'max_chars': 5}, {'answer': True, 'reason': '理由'}),
                 ({'type': 'url'}, 'file:///tmp/source')]
        for index, (fmt, value) in enumerate(cases):
            with self.subTest(fmt=fmt, value=value):
                engine = Engine(f'format{index}', self.root)
                request = self.request(engine.next(sequence=single(fmt=fmt)))
                report = engine.answer(answer(request, value))
                self.assertEqual(0, report['accepted_count'])
                self.assertEqual(2, self.request(report)['attempt'])

    def test_all_four_value_formats_accept(self):
        cases = [({'type': 'text', 'max_chars': 2}, '言葉'),
                 ({'type': 'choice', 'choices': ['時間', '空間']}, '時間'),
                 ({'type': 'boolean_with_reason', 'max_chars': 10}, {'answer': False, 'reason': '時間を使うから。'}),
                 ({'type': 'url'}, 'https://example.invalid/source')]
        for index, (fmt, value) in enumerate(cases):
            engine = Engine(f'valid{index}', self.root)
            request = self.request(engine.next(sequence=single(fmt=fmt)))
            self.assertEqual('COMPLETED', engine.answer(answer(request, value))['status'])

    def test_sequence_and_context_are_pinned_on_resume(self):
        sequence = single(inputs={'seed': {'context': 'seed'}})
        report = self.engine.next(sequence=sequence, context={'seed': '短い材料', 'irrelevant': 'excluded'})
        self.assertEqual({'seed': '短い材料'}, self.request(report)['inputs'])
        sequence['elements'][0]['instruction'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'Sequence differs'):
            self.engine.next(sequence=sequence)
        with self.assertRaisesRegex(ValueError, 'Context differs'):
            self.engine.next(context={'seed': 'Changed'})
        self.assertEqual(report, self.engine.next(registry=Path('missing-registry.yaml')))

    def test_atomic_replace_failure_keeps_replayable_checkpoint(self):
        report = self.engine.next()
        old = self.engine.path.read_bytes()
        with patch('tools.element.os.replace', side_effect=OSError('simulated crash')):
            with self.assertRaises(OSError):
                self.engine.answer(FakeAnswerer().answer(self.request(report)))
        self.assertEqual(old, self.engine.path.read_bytes())
        self.assertEqual(report, Engine('fixture', self.root).next())
        self.assertEqual({'element-state.json', 'element.lock'}, {p.name for p in self.engine.directory.iterdir()})

    def test_external_state_and_path_safe_run_ids(self):
        for bad in ('../escape', '.', '', 'a/b'):
            with self.assertRaises(ValueError):
                Engine(bad, self.root)
        for bad in (ROOT / 'data', Path('relative'), Path('/')):
            with self.assertRaises(ValueError):
                Engine('safe', bad)
        checkout = self.root / 'checkout'
        checkout.mkdir()
        (checkout / '.git').write_text('gitdir: synthetic')
        with self.assertRaises(ValueError):
            Engine('safe', checkout / 'state')
        (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            Engine('alias', self.root)

    def test_bounded_material_never_emits_oversized_request(self):
        with self.assertRaisesRegex(ValueError, 'request budget'):
            self.engine.next(sequence=single(inputs={'huge': {'literal': 'a' * 4096}}))
        self.assertFalse(self.engine.path.exists())

    def test_concurrent_duplicate_answer_is_accepted_once(self):
        request = self.request(self.engine.next())
        command = [sys.executable, 'tools/element.py', 'answer', '--run-id', 'fixture', '--state-root', str(self.root)]
        payload = canonical(FakeAnswerer().answer(request))
        a = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        b = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        a.communicate(payload, timeout=30)
        b.communicate(payload, timeout=30)
        self.assertEqual([0, 0], sorted([a.returncode, b.returncode]))
        self.assertEqual(1, self.engine.status()['accepted_count'])
        self.assertEqual(1, len(json.loads(self.engine.path.read_text())['history']))


class MechanicalChecksTests(unittest.TestCase):
    def test_each_check_passes_and_fails_mechanically(self):
        ledger = {'https://example.invalid/a': {'body': '原文を変えずに引用する。'}}
        inputs = {'operation': '先送り', 'ids': ['event-1'], 'url': 'https://example.invalid/a'}
        cases = [('non_empty', '答え', ' '), ('min_chars:2', '二字', '字'),
                 ('max_chars:2', '二字', '三文字'), ('ends_with_question', '問い？', '平叙文。'),
                 ('contains_terms:operation,時間', '先送りと時間', '時間だけ'),
                 ('forbidden:無し,未記入,∩', '内容', '未記入'), ('one_of:時間,空間', '時間', '人'),
                 ('reference_exists:ids', 'event-1', 'event-2'),
                 ('url_shape', 'https://example.invalid/a', 'not a url'),
                 ('url_in_ledger', 'https://example.invalid/a', 'https://example.invalid/b'),
                 ('exact_excerpt:url', '変えずに引用', '変えず に引用'),
                 ('not_similar:0.8', '全く異なる値', 'already accepted')]
        for check, good, bad in cases:
            with self.subTest(check=check):
                kwargs = dict(inputs=inputs, ledger=ledger, previous_answers={'old': 'already accepted'})
                self.assertEqual([], check_value(good, [check], **kwargs))
                self.assertTrue(check_value(bad, [check], **kwargs))

    def test_similarity_is_deterministic_and_normalized(self):
        self.assertTrue(too_similar('ＡＢＣ  DEF', 'abc def', '1'))
        self.assertFalse(too_similar('abc', 'xyz', '0.5'))
        self.assertEqual(too_similar('abcde', 'cdef', '0.4'), too_similar('cdef', 'abcde', '0.4'))
        self.assertTrue(too_similar('abc', 'abd', '0.333333333333333333333333'))
        self.assertFalse(too_similar('abc', 'abd', '0.333333333333333333333334'))
        with localcontext() as context:
            context.prec = 2
            self.assertFalse(too_similar('abc', 'abd', '0.' + '3' * 90 + '4'))

    def test_url_validation_does_not_need_network_and_rejects_credentials(self):
        for value in ('https://example.invalid/a', 'http://localhost:8080/a'):
            self.assertTrue(valid_url(value))
        for value in ('ftp://example.invalid', 'https://', 'https://a b', 'https://u:p@example.invalid',
                      'https://example.invalid:bad', 'https://example.invalid:0', 'http://[bad',
                      'https://.', 'https://x..y', 'https://-bad.invalid'):
            self.assertFalse(valid_url(value))

    def test_unknown_or_malformed_checks_fail_closed(self):
        for check in ('unknown', 'min_chars:0', 'max_chars:-1', 'contains_terms:', 'forbidden:a,',
                      'not_similar:NaN', 'not_similar:1.1', 'not_similar:0', 'non_empty:x'):
            with self.subTest(check=check), self.assertRaises(ValueError):
                parse_check(check)

    def test_missing_id_or_unretrieved_excerpt_never_pass(self):
        self.assertTrue(check_value('id', ['reference_exists:ids'], inputs={}, ledger={}, previous_answers={}))
        self.assertTrue(check_value('quote', ['exact_excerpt:url'], inputs={'url': 'https://example.invalid'}, ledger={}, previous_answers={}))


class SearchLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.engine = Engine('search-fixture', self.root)
        self.result = {'url': 'https://example.invalid/source', 'title': '合成資料', 'body': '時間をずらす。先送りが残る。'}
        self.sequence = single()
        self.sequence['elements'] = [
            {'kind': 'search', 'element_id': 'lookup', 'query': {'literal': '先送り 時間'}, 'limit': 1},
            single(inputs={'source_url': {'search_result': {'element_id': 'lookup', 'index': 0, 'field': 'url'}}},
                   checks=['exact_excerpt:source_url'])['elements'][0],
        ]

    def test_search_fake_hash_ledger_and_exact_quote_resume(self):
        fake = FakeAnswerer({'lookup': [[self.result]], 'unit.value': ['時間を ずらす。', '時間をずらす。']})
        report = self.engine.next(sequence=self.sequence)
        request = report['next_action']['request']
        self.assertEqual('search-request/v1', request['contract_version'])
        self.assertEqual('先送り 時間', request['query'])
        report = self.engine.answer(fake.answer(request))
        state = json.loads(self.engine.path.read_text())
        entry = state['ledger'][self.result['url']]
        self.assertEqual(hashlib.sha256(self.result['body'].encode()).hexdigest(), entry['body_sha256'])
        self.assertEqual('agentic-art-orchestration', entry['source_repository'])
        self.assertRegex(entry['source_commit'], '^[0-9a-f]{40}$')
        report = self.engine.answer(fake.answer(report['next_action']['request']))
        self.assertEqual('exact_excerpt:source_url', report['next_action']['request']['previous_failure'][0]['check'])
        self.assertEqual(report, Engine('search-fixture', self.root).next())
        report = self.engine.answer(fake.answer(report['next_action']['request']))
        self.assertEqual('COMPLETED', report['status'])

    def test_empty_duplicate_invalid_url_and_excess_results_retry_without_ledger_mutation(self):
        report = self.engine.next(sequence=self.sequence)
        cases = [([], 'non_empty'), ([self.result, self.result], 'unique_urls'),
                 ([{**self.result, 'url': 'file:///invalid'}], 'url_shape'),
                 ([{**self.result, 'body': ' '}], 'non_empty')]
        for values, expected in cases:
            report = self.engine.answer(answer(report['next_action']['request'], values))
            self.assertIn(expected, [f['check'] for f in report['next_action']['request']['previous_failure']])
            self.assertEqual({}, json.loads(self.engine.path.read_text())['ledger'])
        report = self.engine.answer(answer(report['next_action']['request'], []))
        self.assertEqual('BLOCKED', report['status'])

    def test_conflicting_url_body_is_rejected_without_overwriting_pinned_text(self):
        sequence = deepcopy(self.sequence)
        sequence['elements'] = [sequence['elements'][0], {**sequence['elements'][0], 'element_id': 'lookup-again'}]
        report = self.engine.next(sequence=sequence)
        report = self.engine.answer(answer(report['next_action']['request'], [self.result]))
        report = self.engine.answer(answer(report['next_action']['request'], [{**self.result, 'body': 'Changed'}]))
        self.assertEqual('source_conflict', report['next_action']['request']['previous_failure'][0]['check'])
        entry = json.loads(self.engine.path.read_text())['ledger'][self.result['url']]
        self.assertEqual(self.result['body'], entry['body'])

    def test_next_binding_failure_preserves_accepted_search(self):
        sequence = deepcopy(self.sequence)
        sequence['elements'][1]['inputs']['source_url']['search_result']['index'] = 1
        report = self.engine.next(sequence=sequence)
        report = self.engine.answer(answer(report['next_action']['request'], [self.result]))
        self.assertEqual('BLOCKED', report['status'])
        self.assertEqual(1, report['accepted_count'])
        self.assertEqual('input_build', report['blocked']['last_failure'][0]['check'])


class RegistrationAndContractTests(unittest.TestCase):
    def test_validate_entry_exposes_all_four_boundary_validators(self):
        from tools import validate
        validators = (validate.validate_element_request, validate.validate_element_answer,
                      validate.validate_search_request, validate.validate_search_answer)
        for validator in validators:
            self.assertTrue(validator({'contract_version': 'wrong'}))

    def test_validate_checks_schema_identity_and_registry_content(self):
        from tools.element_contracts import schema
        def wrong_identity(name):
            value = schema(name)
            value['$id'] = 'wrong/v1'
            return value
        with patch('tools.element_contracts.schema', side_effect=wrong_identity):
            self.assertTrue(validate_contracts())
        with patch('tools.element_contracts.yaml.safe_load', return_value=single(checks=['unknown'])):
            self.assertTrue(validate_contracts())

    def test_registered_demo_and_all_contracts_are_valid(self):
        self.assertEqual([], validate_contracts())
        sequence = load_sequence()
        self.assertEqual(3, len(sequence['elements']))
        self.assertEqual([], validate_sequence(sequence))

    def test_declarative_binding_references_and_checks_fail_closed(self):
        sequence = load_sequence()
        bad_cases = []
        duplicate = deepcopy(sequence)
        duplicate['elements'][1]['element_id'] = duplicate['elements'][0]['element_id']
        bad_cases.append(duplicate)
        forward = deepcopy(sequence)
        forward['elements'][0]['inputs']['future'] = {'answer': 'demo.question'}
        bad_cases.append(forward)
        unknown = deepcopy(sequence)
        unknown['elements'][0]['checks'].append('model_decides')
        bad_cases.append(unknown)
        missing_key = deepcopy(sequence)
        missing_key['elements'][0]['checks'].append('exact_excerpt:missing')
        bad_cases.append(missing_key)
        multiple_binding = deepcopy(sequence)
        multiple_binding['elements'][0]['inputs']['material']['answer'] = 'demo.operation'
        bad_cases.append(multiple_binding)
        for value in bad_cases:
            self.assertTrue(validate_sequence(value))

    def test_contracts_reject_unknown_fields_wrong_versions_types_and_missing_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine('schema', Path(directory).resolve())
            request = engine.next()['next_action']['request']
        valid = answer(request, '先送り')
        for name, message in [('element-request', request), ('element-answer', valid)]:
            self.assertEqual([], validate_message(message, name))
            for mutation in ('extra', 'version', 'missing', 'attempt'):
                value = deepcopy(message)
                if mutation == 'extra':
                    value['extra'] = 'private rejected value'
                elif mutation == 'version':
                    value['contract_version'] = 'unsupported'
                elif mutation == 'missing':
                    del value['run_id']
                else:
                    value['attempt'] = True
                errors = validate_message(value, name)
                self.assertTrue(errors)
                self.assertNotIn('private rejected value', '; '.join(errors))

    def test_search_schema_contracts_are_closed(self):
        request = {'contract_version': 'search-request/v1', 'run_id': 'fixture', 'element_id': 'lookup',
                   'attempt': 1, 'query': '合成検索', 'limit': 1, 'previous_failure': None}
        response = answer(request, [{'url': 'https://example.invalid/a', 'title': '資料', 'body': '本文'}])
        for name, value in [('search-request', request), ('search-answer', response)]:
            self.assertEqual([], validate_message(value, name))
            self.assertTrue(validate_message({**value, 'extra': True}, name))
        response['results'][0]['extra'] = True
        self.assertTrue(validate_message(response, 'search-answer'))

    def test_bindings_only_send_explicitly_selected_values(self):
        self.assertEqual({'material': 'wanted', 'prior': 'answer'}, build_inputs(
            {'material': {'context': 'selected'}, 'prior': {'answer': 'earlier'}},
            {'earlier': 'answer', 'other': 'excluded'}, {'selected': 'wanted', 'other': 'excluded'}))


class AnswererAndCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def cli(self, command, payload=None):
        # The real wrapper carries stdin/stdout for both run and element CLIs.
        return subprocess.run([sys.executable, 'tools/credential_free.py', '--state-root', str(self.root), '--',
                               sys.executable, *command], cwd=ROOT, input=payload, capture_output=True,
                              text=True, timeout=60)

    def test_credential_free_demo_run_answer_resume_and_status_end_to_end(self):
        command = ['tools/run.py', '--element-demo', '--run-id', 'cli', '--state-root', str(self.root)]
        result = self.cli(command)
        self.assertEqual(0, result.returncode, result.stderr)
        first_bytes = result.stdout
        self.assertEqual(first_bytes, self.cli(command).stdout)
        fake = FakeAnswerer()
        for index in range(3):
            report = json.loads(result.stdout)
            request = report['next_action']['request']
            reply = self.cli(['tools/element_answerer.py', '--fake'], canonical(request))
            self.assertEqual(0, reply.returncode, reply.stderr)
            self.assertEqual(fake.answer(request), json.loads(reply.stdout))
            submitted = self.cli(['tools/element.py', 'answer', '--run-id', 'cli', '--state-root', str(self.root)], reply.stdout)
            self.assertEqual(0, submitted.returncode, submitted.stderr)
            result = self.cli(command)
            self.assertEqual(submitted.stdout, result.stdout)
            self.assertEqual(index + 1, json.loads(result.stdout)['accepted_count'])
        self.assertEqual('COMPLETED', json.loads(result.stdout)['status'])
        status = self.cli(['tools/element.py', 'status', '--run-id', 'cli', '--state-root', str(self.root)])
        self.assertEqual(result.stdout, status.stdout)

    def test_next_answer_and_status_cli_expose_retry_and_block_exit_codes(self):
        command = ['tools/element.py', 'next', '--run-id', 'block-cli', '--state-root', str(self.root)]
        result = self.cli(command)
        for attempt in range(1, 6):
            request = json.loads(result.stdout)['next_action']['request']
            result = self.cli(['tools/element.py', 'answer', '--run-id', 'block-cli', '--state-root', str(self.root)], canonical(answer(request, ' ')))
            self.assertEqual(2 if attempt == 5 else 0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual('BLOCKED', report['status'])
        self.assertEqual('demo.operation', report['blocked']['element_id'])
        result = self.cli(['tools/element.py', 'status', '--run-id', 'block-cli', '--state-root', str(self.root)])
        self.assertEqual(2, result.returncode)
        self.assertEqual(report, json.loads(result.stdout))

    def test_local_command_adapter_uses_one_request_and_one_answer(self):
        engine = Engine('local', self.root)
        report = engine.next()
        local = LocalAnswerer({'contract_version': 'element-answerer/v1', 'command': [sys.executable, 'tools/element_answerer.py', '--fake'], 'timeout_seconds': 10})
        for _ in range(3):
            report = engine.answer(local.answer(report['next_action']['request']))
        self.assertEqual('COMPLETED', report['status'])

    def test_local_adapter_failures_do_not_consume_engine_attempt(self):
        engine = Engine('local-error', self.root)
        request = engine.next()['next_action']['request']
        original = engine.path.read_bytes()
        scripts = ['import sys; sys.exit(7)', 'print("{}\\n{}")', 'print("not json")',
                   'import time; time.sleep(2)',
                   'import json,sys; r=json.load(sys.stdin); print(json.dumps({"contract_version":"element-answer/v1","run_id":"wrong","element_id":r["element_id"],"attempt":r["attempt"],"value":"value"}))']
        for script in scripts:
            local = LocalAnswerer({'contract_version': 'element-answerer/v1', 'command': [sys.executable, '-c', script], 'timeout_seconds': 1})
            with self.assertRaises(ValueError):
                local.answer(request)
            self.assertEqual(original, engine.path.read_bytes())

    def test_adapter_config_rejects_shell_strings_and_unknown_fields(self):
        for command in ('model | parser', []):
            with self.assertRaises(ValueError):
                LocalAnswerer({'contract_version': 'element-answerer/v1', 'command': command, 'timeout_seconds': 1})
        with self.assertRaises(ValueError):
            LocalAnswerer({'contract_version': 'element-answerer/v1', 'command': ['model'], 'timeout_seconds': 1, 'shell': True})

    def test_demo_entry_requires_explicit_state_and_rejects_production_inputs(self):
        for extra in ([], ['--state-root', str(self.root), '--intent', 'production-input'],
                      ['--state-root', str(self.root), '--delivery-target', 'internal']):
            result = self.cli(['tools/run.py', '--element-demo', '--run-id', 'invalid-demo', *extra])
            self.assertEqual(1, result.returncode)
            self.assertFalse((self.root / 'invalid-demo').exists())


if __name__ == '__main__':
    unittest.main()
