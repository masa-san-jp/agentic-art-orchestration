"""AAK-01 acceptance: independently observed corruption, replay and ownership."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import yaml
from tools.issue_intake import (AAK_SPEC, AAK_PLAN, AAK_CONTRACT, ROOT,
    aak_projection, validate_aak_projection, register_aak, IssueIntakeError)
from tools.project_status import _next_task


class KnowledgeCycleContractsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in (AAK_SPEC, AAK_PLAN, AAK_CONTRACT, 'execution/task-queue.yaml'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((ROOT/name).read_bytes())
        self.queue = yaml.safe_load((self.root/'execution/task-queue.yaml').read_text())

    def test_ac1_exact_owner_mapping_and_acyclic_dag(self):
        projection = aak_projection(self.root)
        expected = {
            'agentic-art-orchestration': ['AAK-01','AAK-02','AAK-03','AAK-04'],
            'self-model-notes':['AAK-05'], 'art-history-notes':['AAK-06'],
            'marketing-trends-notes':['AAK-07'], 'agentic-art-research':['AAK-08','AAK-09'],
            'agentic-art-production':['AAK-10','AAK-11'],
            'viewer-response-notes':['AAK-12'], 'agentic-art-project':['AAK-13']}
        for owner, ids in expected.items():
            self.assertEqual(ids,[t['id'] for t in projection['tasks'] if t['owner']==owner])
        self.assertEqual([],validate_aak_projection(self.root, self.queue))
        pending = {t['id']:set(t['depends_on']) for t in projection['tasks']}
        order = []
        while pending:
            ready = sorted(k for k,v in pending.items() if v <= set(order))
            self.assertTrue(ready, 'cycle blocks independent topological traversal')
            order.append(ready[0]);del pending[ready[0]]
        self.assertEqual(['AAK-01','AAK-03','AAK-04'],order[:3])
        self.assertEqual('AAK-02', order[-1])

    def test_ac2_readme_reaches_pinned_ssot_and_next_task(self):
        for name in ['README.md','AGENTS.md','PLANS.md']:
            text = (ROOT/name).read_text()
            self.assertIn(AAK_SPEC,text)
            self.assertIn(AAK_PLAN,text)
            self.assertIn('execution/task-queue.yaml',text)
        aak = [copy.deepcopy(t) for t in self.queue['tasks'] if t['id'].startswith('AAK-')]
        aak[0]['status']='READY'
        self.assertEqual('AAK-01',_next_task(aak))
        aak[0]['status']='DONE'
        self.assertEqual('AAK-03',_next_task(aak))
        aak[2]['status']='DONE'
        self.assertIsNone(_next_task(aak), 'AAK-04 must wait for #190 acceptance evidence')

    def test_ac3_missing_reference_owner_and_hash_are_rejected(self):
        for field,value in [('specification',None),('owner','wrong-owner'),('contract_sha256','0'*64)]:
            with self.subTest(field=field):
                queue = copy.deepcopy(self.queue)
                task = next(t for t in queue['tasks'] if t['id']=='AAK-01')
                task[field] = value
                self.assertTrue(validate_aak_projection(self.root,queue))
        p = self.root / AAK_SPEC
        p.write_text(p.read_text()+'\nchanged\n')
        self.assertTrue(validate_aak_projection(self.root,self.queue))

    def test_ac3_broken_anchor_and_source_cycle_are_rejected(self):
        p = self.root / AAK_PLAN
        original = p.read_text()
        p.write_text(original.replace('## aak-01','## missing-aak-01'))
        with self.assertRaises(IssueIntakeError):aak_projection(self.root)
        changed = original.replace('| [AAK-01](#aak-01) | agentic-art-orchestration | なし | なし |',
            '| [AAK-01](#aak-01) | agentic-art-orchestration | [AAK-03](#aak-03) | なし |')
        changed = changed.replace('前提: なし','前提: [AAK-03](#aak-03)',1)
        p.write_text(changed)
        with self.assertRaisesRegex(IssueIntakeError,'cycle'):aak_projection(self.root)

    def test_ac4_registration_preserves_legacy_and_is_byte_idempotent(self):
        path = self.root/'execution/task-queue.yaml'
        legacy = [t for t in self.queue['tasks'] if not t['id'].startswith('AAK-')]
        baseline = yaml.safe_dump({'tasks':legacy},sort_keys=False).encode()
        path.write_bytes(baseline)
        register_aak(self.root)
        first = path.read_bytes()
        self.assertTrue(first.startswith(baseline))
        register_aak(self.root)
        self.assertEqual(first,path.read_bytes())
        after = yaml.safe_load(first)['tasks']
        self.assertEqual(legacy,after[:len(legacy)])
        self.assertEqual(13,len(after)-len(legacy))
        self.assertFalse(any(t['status']=='DONE' for t in after[len(legacy):]))

    def test_ac3_removing_entire_series_fails_canonical_validator(self):
        from unittest.mock import patch
        from tools.validate import validate_tasks
        path = self.root/'execution/task-queue.yaml'
        self.queue['tasks'] = [t for t in self.queue['tasks'] if not t['id'].startswith('AAK-')]
        path.write_text(yaml.safe_dump(self.queue))
        errors = []
        with patch('tools.validate.ROOT', self.root):
            validate_tasks(errors, path)
        self.assertTrue(any('AAK: missing' in e for e in errors))

    def test_ac4_done_requires_per_acceptance_candidate_evidence(self):
        task = next(t for t in self.queue['tasks'] if t['id']=='AAK-01')
        task['status']='DONE'
        task['acceptance_evidence']={}
        self.assertTrue(validate_aak_projection(self.root,self.queue))

    def test_external_closed_or_pr_only_is_not_ready(self):
        tasks = [{'id':'AAK-03','status':'DONE','depends_on':[]},
            {'id':'AAK-04','status':'BACKLOG','depends_on':['AAK-03'],
            'external_dependencies':['https://github.com/masa-san-jp/agentic-art-orchestration/issues/190'],
            'dependency_evidence':{}}]
        url = tasks[1]['external_dependencies'][0]
        tasks[1]['dependency_evidence'][url]={'status':'CLOSED','pull_request':'#191'}
        self.assertIsNone(_next_task(tasks))

if __name__=='__main__':unittest.main()
