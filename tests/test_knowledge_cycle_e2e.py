"""Synthetic boundary/failure regressions; these do not stand in for live agents."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import knowledge_cycle_run as cycle
from tools import native_knowledge
from tools.autonomous_runner import _new_state, _apply_result, validate_autonomous_state
from tools.knowledge_cycle import LocalOwner
from tools.plan_completion import PlanCompletionError, verify_plan


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()


def init_code(root):
    root.mkdir(parents=True)
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Synthetic')
    git(root, 'config', 'user.email', 'synthetic@example.invalid')


class KnowledgeCycleE2ETests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def plan(self):
        code = self.root / 'code'
        init_code(code)
        (code / 'tools').mkdir()
        # Independent synthetic owner oracle, exercising subprocess/pin and file boundaries.
        (code / 'tools/plan_actionability.py').write_text('''import json,sys
from pathlib import Path
p=Path(sys.argv[sys.argv.index('--project-root')+1])
a=json.loads((p/'03_plan/production-plan.yaml').read_text())
ok=(p/'03_plan/production-plan.md').read_text()==a['canonical_text'] and (p/'03_plan/media/board.svg').read_text()==a['asset']
print(json.dumps({'contract_version':'plan-actionability/v1','plan_status':'PLAN_READY' if ok else 'INCOMPLETE','findings':[] if ok else ['TAMPER']}))
raise SystemExit(0 if ok else 1)
''')
        git(code, 'add', '.')
        git(code, 'commit', '-qm', 'synthetic qualified owner')
        project = self.root / 'internal/production/synthetic'
        (project / '03_plan/media').mkdir(parents=True)
        (project / '02_specification').mkdir()
        (project / '03_plan/production-plan.md').write_text('# Prepare paper\nCut two 20 cm panels and compare their shadow spacing.\n')
        (project / '03_plan/media/board.svg').write_text('<svg>synthetic</svg>')
        (project / '03_plan/production-plan.yaml').write_text(json.dumps({'canonical_text': (project / '03_plan/production-plan.md').read_text(), 'asset': '<svg>synthetic</svg>'}))
        (project / '02_specification/production-method.yaml').write_text('synthetic: explicit proposal\n')
        sha = git(code, 'rev-parse', 'HEAD')
        (project / '00_handoff').mkdir()
        (project / '00_handoff/production-handoff.yaml').write_text(json.dumps({'research_commit':sha}))
        return code, sha, project

    def test_ac3_success_json_empty_summary_tamper_and_dirty_code_fail_closed(self):
        code, sha, project = self.plan()
        kwargs = dict(code_root=code, code_commit=sha, project_root=project)
        with self.assertRaisesRegex(PlanCompletionError, 'RESEARCH_HANDOFF_PIN_MISMATCH'):
            verify_plan(**kwargs, research_commit='f'*40)
        verified = verify_plan(**kwargs, research_commit=sha)
        self.assertEqual('PLAN_READY', verified['plan_status'])
        md = project / '03_plan/production-plan.md'
        original = md.read_bytes()
        for replacement in [b'', b'{"status":"COMPLETED"}', b'# Summary\n']:
            md.write_bytes(replacement)
            with self.assertRaises(PlanCompletionError):
                verify_plan(**kwargs)
        md.write_bytes(original)
        asset = project / '03_plan/media/board.svg'
        asset.write_text('<svg>altered</svg>')
        with self.assertRaises(PlanCompletionError):
            verify_plan(**kwargs, expected=verified['artifacts'])
        asset.write_text('<svg>synthetic</svg>')
        (code / 'unreviewed.py').write_text('pass\n')
        with self.assertRaisesRegex(PlanCompletionError, 'CLEANLINESS'):
            verify_plan(**kwargs)

    def test_ac3_worker_report_never_attests_production_and_old_false_success_is_rejected(self):
        state = _new_state('synthetic', 'agentic-art-research', 'a'*40, 'project', ['project'], '2026-09-08T00:00:00Z')
        state['attempts'] = 1
        _apply_result(state, {'status': 'COMPLETED', 'requested_operations': [], 'changed_paths': []}, 'b'*64)
        self.assertEqual('RESEARCH_COMPLETE', state['status'])
        self.assertEqual('research', state['stage'])
        state.update(status='PLAN_READY', stage='plan')
        self.assertTrue(any('canonical Production' in e for e in validate_autonomous_state(state)))

    def test_native_initializer_preserves_owner_git_and_failed_initialization_retries(self):
        store = self.root / 'owner'
        calls = []
        def initialize(path):
            calls.append(str(path))
            if len(calls) == 1:
                path.mkdir()
                (path / 'partial').write_text('incomplete')
                raise ValueError('synthetic initializer interruption')
            subprocess.run(['git', 'init', '--bare', '-q', str(path)], check=True)
            env = dict(os.environ, GIT_AUTHOR_NAME='Synthetic', GIT_AUTHOR_EMAIL='s@example.invalid', GIT_COMMITTER_NAME='Synthetic', GIT_COMMITTER_EMAIL='s@example.invalid')
            tree = subprocess.check_output(['git', '--git-dir', str(path), 'mktree'], input=b'').decode().strip()
            commit = subprocess.check_output(['git', '--git-dir', str(path), 'commit-tree', tree], input=b'native identity', env=env).decode().strip()
            subprocess.run(['git', '--git-dir', str(path), 'update-ref', 'refs/heads/knowledge', commit], check=True)
        args = (store, 'agentic-art-production', 'synthetic', 'a'*40)
        with self.assertRaises(ValueError):
            LocalOwner(*args, creator='synthetic', payload_validator=lambda *_: False, initializer=initialize)
        self.assertFalse(any(store.iterdir()))
        owner = LocalOwner(*args, creator='synthetic', payload_validator=lambda *_: False, initializer=initialize)
        reopened = LocalOwner(*args, creator='synthetic', payload_validator=lambda *_: False, initializer=lambda _: self.fail('must not initialize twice'))
        self.assertEqual(owner.knowledge_commit, reopened.knowledge_commit)
        self.assertEqual(2, len(calls))

    def test_native_command_binds_identity_and_forbids_arbitrary_or_project_writes(self):
        b = {'store_root': str(self.root / 'store'), 'creator': 'creator', 'collection': 'collection', 'code_commit': 'a'*40}
        args = dict(snapshot='b'*40, run_id='run', operation_id='op', clock='2026-09-08T00:00:00Z')
        with self.assertRaises(native_knowledge.NativeKnowledgeError):
            native_knowledge.command('agentic-art-research', b, 'write', {'creator': 'someone-else'}, **args)
        with self.assertRaises(native_knowledge.NativeKnowledgeError):
            native_knowledge.command('agentic-art-project', b, 'write', {}, **args)
        with self.assertRaises(native_knowledge.NativeKnowledgeError):
            native_knowledge.command('agentic-art-research', b, 'write', {'candidate': '--help'}, **args)
        result = native_knowledge.command('agentic-art-research', b, 'write', {'candidate': str(self.root / 'candidate.json')}, **args)
        self.assertIn('creator', result)
        self.assertIn('b'*40, result)
        self.assertNotIn('shell', result)

    def test_ac4_ac5_partial_write_resume_retains_plan_and_successful_owner_receipt(self):
        code, sha, project = self.plan()
        state = {'run_id':'run', 'queries':{}, 'owners':{}, 'attempts':{}, 'plan':None, 'plan_status':'RESEARCH_PENDING', 'knowledge_status':'PENDING', 'run_status':'RUNNING'}
        context = {'run_id':'run', 'clock':'2026-09-08T00:00:00Z', 'query_inputs':{}, 'write_inputs':{}}
        bindings, refs, writes = {}, {}, {}
        for owner in cycle.OWNERS:
            store = self.root / 'stores' / owner
            provider = LocalOwner(store, owner, owner, sha, creator='creator', payload_validator=lambda *_: False)
            bindings[owner] = {'code_root':str(code), 'code_commit':sha, 'store_root':str(store), 'collection':owner, 'creator':'creator'}
            refs[owner] = {'commit':provider.knowledge_commit}
            q = self.root / (owner+'-query.json'); q.write_text('{}')
            context['query_inputs'][owner] = str(q)
            if owner != 'agentic-art-project':
                job = {'action':'write' if owner in {'agentic-art-research','agentic-art-production'} else 'no-new-evidence', 'inputs':{}, 'reason':'synthetic evidence decision'}
                p = self.root / (owner+'-write.json'); p.write_text(json.dumps(job)); context['write_inputs'][owner] = str(p)
        failed = [False]
        def native(owner,binding,action,inputs,**kwargs):
            if action == 'query': return {'snapshot':kwargs['snapshot'],'records':[]}
            if action == 'index': return {'index_commit':kwargs['snapshot'],'index_hash':'c'*64}
            writes[owner] = writes.get(owner,0)+1
            if owner == 'agentic-art-production' and not failed[0]:
                failed[0] = True
                raise native_knowledge.NativeKnowledgeError('SYNTHETIC_OWNER_FAILURE')
            parent = kwargs['snapshot']
            return {'contract_version':'knowledge-write-receipt/v1','operation_id':kwargs['operation_id'],'run_id':'run','owner':owner,'collection':owner,'target_parent':parent,'target_commit':parent,'accepted_ids':['synthetic-proposal'],'rejected_ids':[],'schema_version':'synthetic/v1','policy_version':'synthetic/v1','index_commit':parent,'index_hash':'c'*64,'status':'ALREADY_APPLIED','reason':'synthetic receipt for boundary recovery test'}
        profile = {'delivery_mode':'internal','permissions':{'local_git_commit':True,'local_knowledge_write':True}}
        arguments = (context,profile,{'knowledge_refs':refs,'code_refs':{'agentic-art-research':{'commit':sha}}},bindings,project,state,self.root/'run')
        with patch.object(cycle, 'invoke', side_effect=native):
            cycle._advance(*arguments)
            self.assertEqual('PLAN_READY',state['plan_status'])
            self.assertEqual('PARTIAL',state['knowledge_status'])
            self.assertEqual('INCOMPLETE',state['run_status'])
            prior = copy.deepcopy(state['owners']['agentic-art-research'])
            cycle._advance(*arguments)
            self.assertEqual(prior,state['owners']['agentic-art-research'])
            self.assertEqual(2,writes['agentic-art-research'])
            self.assertEqual(2,writes['agentic-art-production'])
            self.assertEqual('COMPLETED',state['run_status'])
            self.assertEqual('SKIPPED',state['projection_status'])
            cycle._advance(*arguments)
            self.assertEqual(3,writes['agentic-art-production'])
            p=Path(context['write_inputs']['agentic-art-research']); job=json.loads(p.read_text());job['reason']='changed after commit';p.write_text(json.dumps(job))
            with self.assertRaisesRegex(ValueError,'COMPLETED_OWNER_INPUT_CHANGED'):
                cycle._advance(*arguments)

    def test_ac5_public_projection_requires_native_receiver_attribution(self):
        run_root=self.root/'state/knowledge-cycles/run'
        project=self.root/'internal/production/proposal'
        resolution={'destination_resolution':{'destinations':{'internal_output_root':{'path':str(self.root/'internal')},'public_projection_root':{'path':str(self.root/'catalog')}}}}
        context={'run_id':'run','clock':'2026-09-08T00:00:00Z'}
        profile={'creator_id':'creator','instance_id':'origin'}
        bindings={'agentic-art-production':{'code_commit':'a'*40,'code_root':str(self.root/'code')},'agentic-art-project':{}}
        state={'plan_status':'PLAN_READY','knowledge_status':'COMMITTED','plan':{'artifacts':{'03_plan/production-plan.md':'b'*64}}}
        receipt={'status':'BLOCKED_POLICY','result_locator':'run/public-projection-result.json','public_ids':[]}
        record={'record_id':'P0001','content_sha256':'b'*64,'creator_id':'other','origin_instance_id':'inherited','source_identity':'production/proposal#PL001'}
        with patch('tools.canonical_plan_projection.source_fields',return_value={'source_identity':record['source_identity']}), patch('tools.public_projection.build_automatic_plan_authority',return_value={}), patch('tools.public_projection.project_plan_automatic',side_effect=lambda *a,**k:copy.deepcopy(receipt)), patch.object(cycle.subprocess,'check_output',return_value='c'*40), patch.object(cycle,'invoke',side_effect=lambda *a,**k:{'records':[copy.deepcopy(record)]}):
            cycle._public_completion(context,profile,resolution,bindings,project,state,run_root)
            self.assertEqual('INCOMPLETE',state['run_status'])
            self.assertEqual('BLOCKED',state['projection_status'])
            receipt.update(status='APPLIED',public_ids=['P0001'])
            cycle._public_completion(context,profile,resolution,bindings,project,state,run_root)
            self.assertEqual('PROJECT_LINEAGE_NOT_VERIFIED',state['stop_reason'])
            record.update(creator_id='creator',origin_instance_id='origin')
            cycle._public_completion(context,profile,resolution,bindings,project,state,run_root)
            self.assertEqual('PROJECTED',state['projection_status'])
            self.assertEqual('COMPLETED',state['run_status'])

    def test_cache_parent_symlink_cannot_escape_the_selected_owner(self):
        outside=self.root/'outside';outside.mkdir()
        (self.root/'cache').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(native_knowledge.NativeKnowledgeError):
            cycle.save(self.root/'cache/result.json',{'status':'COMPLETED'})
        self.assertEqual([],list(outside.iterdir()))


if __name__ == '__main__':
    unittest.main()
