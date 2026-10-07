import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import self_hearing
from tools.hearing_elements import relay, supports


class PrivateHearingElementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.checkout = self.root / 'workspace/self-model-notes'
        (self.checkout / 'tools').mkdir(parents=True)
        (self.checkout / 'tools/growth_tasks.py').write_text('')
        self.request = {'contract_version': 'element-request/v1', 'run_id': 'relay',
                        'element_id': 'A1.claim', 'attempt': 1,
                        'instruction': 'PRIVATE_OWNER_INSTRUCTION', 'inputs': {'event': 'PRIVATE_OWNER_EVENT'},
                        'answer_format': {'type': 'text', 'max_chars': 120},
                        'checks': ['non_empty'], 'previous_failure': None}

    def child(self, command, **kwargs):
        if '--help' in command:
            return subprocess.CompletedProcess(command, 0, 'next answer', '')
        if 'answer' in command:
            self.assertIs(kwargs['stdin'], sys.stdin)
        return subprocess.CompletedProcess(command, 0, json.dumps({
            'status': 'WAITING', 'next_action': {'kind': 'element', 'request': self.request},
            'answers': ['PRIVATE_ANSWER'], 'diagnostic': 'PRIVATE_DIAGNOSTIC'}), '')

    def test_compatible_owner_request_is_private_and_not_persisted(self):
        with patch('tools.hearing_elements.subprocess.run', side_effect=self.child), \
             patch('tools.self_hearing.observe_git_write_credentials', return_value='absent'):
            code, stdout, outcome = self_hearing.execute('open', run_id='relay', state_root=self.root / 'state',
                 workspace_root=self.root / 'workspace', profile_root=self.root / 'profile')
        self.assertEqual(0, code)
        action = json.loads(stdout)['next_action']
        self.assertTrue(action['private'])
        self.assertTrue(action['request']['private'])
        self.assertEqual('offered', outcome['outcome'])
        saved = '\n'.join(path.read_text() for path in (self.root / 'state').rglob('*.json'))
        for private in ('PRIVATE_OWNER_EVENT', 'PRIVATE_OWNER_INSTRUCTION', 'PRIVATE_ANSWER', 'PRIVATE_DIAGNOSTIC'):
            self.assertNotIn(private, saved)
        progress = json.loads((self.root / 'state/relay/hearing-element.json').read_text())
        self.assertEqual({'private', 'status', 'run_id', 'element_id', 'attempt'}, set(progress))

    def test_owner_answer_streams_stdin_and_state_keeps_progress_only(self):
        progress_path = self.root / 'state/relay/hearing-element.json'
        progress_path.parent.mkdir(parents=True)
        progress_path.write_text(json.dumps({'private': True, 'status': 'WAITING', 'run_id': 'relay',
                                             'element_id': 'A1.claim', 'attempt': 1}))
        self.request['attempt'] = 2
        # StringIO itself cannot be passed to a subprocess; the transport mock
        # proves the wrapper passes the same unparsed stdin object to the owner.
        stdin = io.StringIO('PRIVATE_RAW_RESPONSE')
        with patch('sys.stdin', stdin), patch('tools.hearing_elements.subprocess.run', side_effect=self.child), \
             patch('tools.self_hearing.observe_git_write_credentials', return_value='absent'):
            code, stdout, _ = self_hearing.execute('answer', run_id='relay', state_root=self.root / 'state',
                  workspace_root=self.root / 'workspace', profile_root=self.root / 'profile')
        self.assertEqual(0, code)
        self.assertEqual(2, json.loads(stdout)['next_action']['request']['attempt'])
        self.assertNotIn('PRIVATE_RAW_RESPONSE', progress_path.read_text())
        self.assertNotIn('PRIVATE_ANSWER', stdout)

    def test_old_cli_falls_back_to_existing_hearing(self):
        def old(command, **kwargs):
            if 'element' in command:
                return subprocess.CompletedProcess(command, 2, '', 'unrecognized command')
            self.assertIn('hearing', command)
            return subprocess.CompletedProcess(command, 0, json.dumps({'outcome': 'offered', 'reason': None,
                                       'question_id': 'old-question', 'question': 'PRIVATE_OLD_QUESTION'}), '')
        with patch('tools.hearing_elements.subprocess.run', side_effect=old), \
             patch('tools.self_hearing.observe_git_write_credentials', return_value='absent'):
            code, stdout, outcome = self_hearing.execute('open', run_id='old', state_root=self.root / 'state',
                workspace_root=self.root / 'workspace', profile_root=self.root / 'profile')
        self.assertEqual(0, code)
        self.assertEqual('offered', outcome['outcome'])
        self.assertIn('PRIVATE_OLD_QUESTION', stdout)
        self.assertFalse((self.root / 'state/old/hearing-element.json').exists())

    def test_common_engine_rejects_private_requests_before_retaining_them(self):
        from tools.element import Engine
        from tools.element_contracts import load_sequence
        sequence = load_sequence()
        sequence['elements'][0]['private'] = True
        engine = Engine('private', self.root / 'state')
        with self.assertRaisesRegex(ValueError, 'Private'):
            engine.next(sequence=sequence)
        self.assertFalse(engine.path.exists())

    def test_malformed_sequence_still_raises_contract_error_without_retaining_state(self):
        from tools.element import Engine
        for index, sequence in enumerate(([], {'elements': None}, {'elements': [None]})):
            engine = Engine(f'malformed-{index}', self.root / 'state')
            with self.assertRaises(ValueError):
                engine.next(sequence=sequence)
            self.assertFalse(engine.path.exists())

    def test_private_later_registry_item_is_rejected_before_retaining_sequence(self):
        from tools.element import Engine
        from tools.element_contracts import load_sequence
        sequence = load_sequence()
        sequence['elements'][-1]['private'] = True
        engine = Engine('private-registry', self.root / 'state')
        with patch('tools.element.load_sequence', return_value=sequence), self.assertRaisesRegex(ValueError, 'Private'):
            engine.next()
        self.assertFalse(engine.path.exists())

    def test_private_failure_diagnostics_are_not_echoed_or_saved(self):
        def failure(command, **kwargs):
            if '--help' in command:
                return subprocess.CompletedProcess(command, 0, 'next answer', '')
            return subprocess.CompletedProcess(command, 9, 'PRIVATE_FAIL_STDOUT', 'PRIVATE_FAIL_STDERR')
        with patch('tools.hearing_elements.subprocess.run', side_effect=failure), \
             patch('tools.self_hearing.observe_git_write_credentials', return_value='absent'):
            code, stdout, outcome = self_hearing.execute('open', run_id='fail', state_root=self.root / 'state',
                workspace_root=self.root / 'workspace', profile_root=self.root / 'profile')
        self.assertEqual(0, code)
        self.assertEqual('unavailable', outcome['outcome'])
        self.assertEqual('', stdout)
        self.assertNotIn('PRIVATE_FAIL', canonical(outcome))

    def test_capability_probe_timeout_and_old_owner_return_false(self):
        with patch('tools.hearing_elements.subprocess.run', side_effect=subprocess.TimeoutExpired('probe', 1)):
            self.assertFalse(supports(self.checkout, 1))
        with patch('tools.hearing_elements.subprocess.run', return_value=subprocess.CompletedProcess([], 2, '', '')):
            self.assertFalse(supports(self.checkout, 1))

    def test_terminal_owner_progress_has_no_answers_in_stdout(self):
        for status in ('COMPLETED', 'BLOCKED'):
            with patch('tools.hearing_elements.subprocess.run', return_value=subprocess.CompletedProcess([], 0,
                       json.dumps({'status': status, 'answers': ['PRIVATE_RAW']}), '')):
                report, progress = relay(self.checkout, 'next', profile_root=self.root / 'profile', run_id='r',
                                         purpose='artistic-research', timeout=1)
            self.assertEqual(status, progress['status'])
            self.assertNotIn('PRIVATE_RAW', json.dumps(report))


    def test_owner_question_states_are_private_single_actions_without_saved_words(self):
        for status, operation, fmt in (('HEARING', 'respond', 'event-block'),
                                        ('SEED_REQUIRED', 'respond', 'event-block'),
                                        ('CONFIRMATION', 'confirm', 'yes-no')):
            child = {'status': status, 'next_action': {'kind': 'hearing', 'question': 'PRIVATE_QUESTION？',
                     'why': 'PRIVATE_WHY', 'answer_format': fmt}, 'draft': 'PRIVATE_DRAFT'}
            with patch('tools.hearing_elements.subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(child), '')), \
                 patch('tools.self_hearing.observe_git_write_credentials', return_value='absent'):
                code, stdout, outcome = self_hearing.execute('open', run_id='relay', state_root=self.root / 'state',
                    workspace_root=self.root / 'workspace', profile_root=self.root / 'profile')
            self.assertEqual(0, code)
            action = json.loads(stdout)['next_action']
            self.assertEqual('PRIVATE_QUESTION？', action['question'])
            self.assertEqual(operation, action['operation'])
            self.assertTrue(action['private'])
            self.assertEqual('offered', outcome['outcome'])
            saved = ''.join(p.read_text() for p in (self.root / 'state').rglob('*.json'))
            self.assertNotIn('PRIVATE_', saved)
            self.assertNotIn('PRIVATE_DRAFT', stdout)

    def test_native_operations_runtime_subject_and_stdin(self):
        (self.checkout / 'tools/agent_runtime.py').write_text('')
        for operation in ('next', 'answer', 'respond', 'confirm', 'skip'):
            with patch('tools.hearing_elements.subprocess.run', return_value=subprocess.CompletedProcess([], 0,
                    json.dumps({'status': 'COMPLETED'}), '')) as child:
                relay(self.checkout, operation, profile_root=self.root / 'profile', run_id='relay',
                      purpose='artistic-research', timeout=1, owner_answer='yes', subject='subject/synthetic')
            command = child.call_args.args[0]
            self.assertEqual(str(self.checkout / 'tools/agent_runtime.py'), command[1])
            self.assertIn('--run-id', command)
            self.assertNotIn('--requester', command)
            self.assertIn('subject/synthetic', command)
            self.assertIs(sys.stdin if operation in {'answer', 'respond'} else subprocess.DEVNULL,
                          child.call_args.kwargs['stdin'])
            if operation == 'confirm':
                self.assertEqual('yes', command[command.index('--owner-answer') + 1])

    def test_rejected_answer_reacquires_current_position_without_diagnostics(self):
        with patch('tools.hearing_elements.subprocess.run', side_effect=[
                subprocess.CompletedProcess([], 2, '', 'PRIVATE_REJECTED_INPUT'),
                subprocess.CompletedProcess([], 0, json.dumps({'status': 'WAITING',
                    'next_action': {'kind': 'element', 'request': self.request}}), '')]) as child:
            report, progress = relay(self.checkout, 'answer', profile_root=self.root / 'profile', run_id='relay',
                                     purpose='artistic-research', timeout=1)
        self.assertEqual('ELEMENT_OPERATION_REJECTED', report['operation_error'])
        self.assertEqual(1, progress['attempt'])
        self.assertIn('next', child.call_args.args[0])
        self.assertNotIn('PRIVATE_REJECTED_INPUT', json.dumps(report))

    def test_blocked_preserves_transient_failures_and_exit_two(self):
        child = {'status': 'BLOCKED', 'blocked': {'element_id': 'A1.claim', 'failures': ['PRIVATE_FAILURE']}}
        with patch('tools.hearing_elements.supports', return_value=True), \
             patch('tools.hearing_elements.subprocess.run', return_value=subprocess.CompletedProcess([], 2, json.dumps(child), '')), \
             patch('tools.self_hearing.observe_git_write_credentials', return_value='absent'):
            code, stdout, outcome = self_hearing.execute('open', run_id='relay', state_root=self.root / 'state',
                 workspace_root=self.root / 'workspace', profile_root=self.root / 'profile')
        self.assertEqual(2, code)
        self.assertEqual(child['blocked'], json.loads(stdout)['blocked'])
        self.assertEqual('PRIVATE_ELEMENT_BLOCKED', outcome['reason'])
        saved = ''.join(p.read_text() for p in (self.root / 'state').rglob('*.json'))
        self.assertNotIn('PRIVATE_FAILURE', saved)

def canonical(value):
    return json.dumps(value, ensure_ascii=False)


class PrivateHearingSkipTests(unittest.TestCase):
    def test_private_skip_uses_native_owner_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            checkout = root / 'workspace/self-model-notes/tools'
            checkout.mkdir(parents=True)
            (checkout / 'growth_tasks.py').write_text('')
            progress = root / 'state/skip/hearing-element.json'
            progress.parent.mkdir(parents=True)
            progress.write_text(json.dumps({'private': True, 'status': 'WAITING', 'run_id': 'owner-run',
                                            'element_id': 'A1.claim', 'attempt': 1}))
            with patch('tools.self_hearing.observe_git_write_credentials', return_value='absent'), \
                 patch('tools.hearing_elements.subprocess.run', return_value=subprocess.CompletedProcess([], 0,
                       json.dumps({'status': 'SKIPPED', 'next_action': None}), '')) as child:
                code, stdout, outcome = self_hearing.execute('skip', run_id='skip', state_root=root / 'state',
                    workspace_root=root / 'workspace', profile_root=root / 'profile', reason='no-response')
            self.assertEqual(0, code)
            self.assertEqual('skipped', outcome['outcome'])
            self.assertEqual('SKIPPED', json.loads(progress.read_text())['status'])
            self.assertIn('skip', child.call_args.args[0])
            self.assertIn('--run-id', child.call_args.args[0])


class RunPrivateHearingTests(unittest.TestCase):
    def test_run_exposes_owner_action_after_writing_only_progress(self):
        from tools.run import _run_orchestration
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            action = {'kind': 'hearing', 'private': True, 'question': 'PRIVATE_OWNER_QUESTION？',
                      'why': 'PRIVATE_WHY', 'answer_format': 'event-block', 'operation': 'respond'}
            with patch('tools.run._prepare_runtime_workspace', return_value=({'status': 'PASSED'}, root / 'workspace')), \
                 patch('tools.self_hearing.execute', return_value=(0, json.dumps({'status': 'HEARING', 'next_action': action}), {})), \
                 patch('tools.run._run_tool') as ingest:
                report = _run_orchestration(None, root / 'workspace', root / 'state', 'private-run',
                    'artistic-research', None, None, '2026-10-08T00:00:00Z', sys.executable,
                    research_root=root / 'research', production_root=root / 'production', profile_root=root / 'profile')
            self.assertEqual('HEARING', report['status'])
            self.assertEqual('PRIVATE_OWNER_QUESTION？', report['next_action']['question'])
            self.assertIn('resume_command', report['next_action'])
            saved = (root / 'state/private-run/run.json').read_text()
            self.assertNotIn('PRIVATE_', saved)
            self.assertNotIn('next_action', json.loads(saved))
            ingest.assert_not_called()

    def test_same_run_reacquires_private_progress_before_ingest(self):
        from tools.run import _run_orchestration
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            work = root / 'state/resume'
            work.mkdir(parents=True)
            (work / 'hearing.json').write_text(json.dumps({'outcome': 'offered'}))
            (work / 'hearing-element.json').write_text(json.dumps({'private': True, 'status': 'CONFIRMATION'}))
            with patch('tools.run._prepare_runtime_workspace', return_value=({'status': 'PASSED'}, root / 'workspace')), \
                 patch('tools.self_hearing.execute', return_value=(0, json.dumps({'status': 'CONFIRMATION',
                    'next_action': {'kind': 'hearing', 'private': True, 'question': 'PRIVATE_CONFIRM？'}}), {})) as child:
                report = _run_orchestration(None, root / 'workspace', root / 'state', 'resume',
                    'artistic-research', None, None, '2026-10-08T00:00:00Z', sys.executable,
                    research_root=root / 'research', production_root=root / 'production', profile_root=root / 'profile')
            self.assertEqual('next', child.call_args.args[0])
            self.assertEqual('CONFIRMATION', report['status'])
            self.assertNotIn('PRIVATE_', (work / 'run.json').read_text())

    def test_failed_reacquisition_keeps_existing_private_flow_blocked(self):
        from tools.run import _run_orchestration
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            work = root / 'state/resume'
            work.mkdir(parents=True)
            (work / 'hearing.json').write_text(json.dumps({'outcome': 'offered'}))
            (work / 'hearing-element.json').write_text(json.dumps({'private': True, 'status': 'WAITING'}))
            with patch('tools.run._prepare_runtime_workspace', return_value=({'status': 'PASSED'}, root / 'workspace')), \
                 patch('tools.self_hearing.execute', return_value=(0, '', {'outcome': 'unavailable'})), \
                 patch('tools.run._run_tool') as ingest:
                report = _run_orchestration(None, root / 'workspace', root / 'state', 'resume',
                    'artistic-research', None, None, '2026-10-08T00:00:00Z', sys.executable,
                    research_root=root / 'research', production_root=root / 'production', profile_root=root / 'profile')
            self.assertEqual('BLOCKED', report['status'])
            self.assertEqual('PRIVATE_ELEMENT_UNAVAILABLE', report['blocked']['reason'])
            ingest.assert_not_called()
