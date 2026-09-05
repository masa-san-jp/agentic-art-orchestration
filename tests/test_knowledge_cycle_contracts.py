"""AAK-01 acceptance: independently observed corruption, replay and ownership."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import yaml
from tools.knowledge_cycle import LocalOwner, KnowledgeCycleError, dispatch, prepare
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
        for task in aak:
            if task['id'] != 'AAK-01':
                task['status'] = 'BACKLOG'
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


class AAK03KnowledgeCycleTests(unittest.TestCase):
    OWNERS = ["self-model-notes", "art-history-notes", "marketing-trends-notes",
              "agentic-art-research", "agentic-art-production", "viewer-response-notes",
              "agentic-art-project", "agentic-art-orchestration"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def record(self, owner, rid="r1", revision=1, lifecycle="accepted", invalidates=None):
        payload = (owner + rid).encode()
        import hashlib
        return {"contract_version":"artifact-record/v1", "record_id":rid, "revision":revision,
          "origin_instance_id":"instance-a", "creator_id":"creator-a", "owner_repository":owner,
          "collection_id":"collection-a", "kind":"test-record", "payload_schema":"test/v1",
          "payload_ref":"payloads/"+rid+".json", "content_sha256":hashlib.sha256(payload).hexdigest(),
          "sources":[], "derived_from":[], "epistemic_status":"observed", "lifecycle":lifecycle,
          "applicability":{}, "rights":{}, "access_scope":"private-a", "consent_ref":"consent-a",
          "created_at":"2026-09-05T00:00:00Z", "reviewed_at":None, "valid_until":None,
          "producer":{"kind":"test","run_id":"run-1"}, "supersedes":[], "invalidates":invalidates or []}

    def provider(self, owner):
        return LocalOwner(self.root/owner, owner, "collection-a", "a"*40, "b"*40)

    def test_aak_03_ac1_all_eight_owners_commit_index_retrieve(self):
        providers={o:self.provider(o) for o in self.OWNERS}
        bundles=[prepare([self.record(o)],o,"collection-a","op-"+o,"run-1") for o in self.OWNERS]
        report=dispatch(bundles,providers)
        self.assertEqual("COMMITTED",report["status"]); self.assertEqual(8,len(report["receipts"]))
        for owner, provider in providers.items():
            trace=provider.retrieve("next-hypothesis","creator-a","private-a")
            self.assertEqual("REUSED",trace["status"]); self.assertEqual(owner,trace["records"][0]["owner"])
            self.assertEqual("a"*40,trace["input_snapshot"]["code_commit"])

    def test_aak_03_ac2_replay_conflict_owner_candidate_and_path_fail_closed(self):
        p=self.provider(self.OWNERS[0]); record=self.record(self.OWNERS[0]); bundle=prepare([record],self.OWNERS[0],"collection-a","op-1","run-1")
        first=p.index(p.commit(bundle,p.knowledge_commit)); self.assertEqual("COMMITTED",first["status"])
        replay=p.commit(bundle,"b"*40); self.assertEqual("ALREADY_APPLIED",replay["status"])
        target=p.records/"instance-a--self-model-notes--r1--r1.json"
        changed=dict(record); changed["kind"]="different"; target.write_bytes(__import__('tools.knowledge_cycle',fromlist=['canonical']).canonical(changed))
        other=self.provider(self.OWNERS[0]); other.root=p.root; other.records=p.records; other.receipts=self.root/"new-receipts"; other.index_path=p.index_path
        conflict=other.commit(prepare([record],self.OWNERS[0],"collection-a","op-2","run-1"),other.knowledge_commit)
        self.assertEqual("CONFLICT",conflict["status"])
        for field,value in [("owner_repository","wrong"),("lifecycle","candidate"),("payload_ref","../escape")]:
            bad=dict(record);bad[field]=value
            receipt=other.commit(prepare([bad],self.OWNERS[0],"collection-a","bad-"+field,"run-1"),other.knowledge_commit)
            self.assertEqual("REJECTED",receipt["status"])

    def test_aak_03_ac3_partial_keeps_success_and_resumes_only_pending(self):
        providers={o:self.provider(o) for o in self.OWNERS[:2]}; bundles=[prepare([self.record(o)],o,"collection-a","op-"+o,"run-1") for o in providers]
        report=dispatch(bundles,providers,fail_owner=self.OWNERS[1]); self.assertEqual("PARTIAL",report["status"])
        self.assertEqual([self.OWNERS[1]],report["pending_owners"])
        self.assertTrue(providers[self.OWNERS[0]].index_path.exists()); self.assertTrue(providers[self.OWNERS[1]].records.exists())
        resumed=providers[self.OWNERS[1]].index(report["receipts"][1]); self.assertIsNotNone(resumed["index_hash"])

    def test_aak_03_ac4_invalidation_excludes_active_and_preserves_revalidation(self):
        p=self.provider(self.OWNERS[0]); base=self.record(self.OWNERS[0],"old")
        receipt=p.index(p.commit(prepare([base],p.owner,p.collection,"op-old","run-1"),p.knowledge_commit))
        invalidator=self.record(p.owner,"revoke",invalidates=[{"record_id":"old","revision":1}])
        receipt=p.index(p.commit(prepare([invalidator],p.owner,p.collection,"op-revoke","run-2"),p.knowledge_commit))
        trace=p.retrieve("next","creator-a","private-a")
        self.assertNotIn("old",[r["record_id"] for r in trace["records"]])
        index=json.loads(p.index_path.read_text()); self.assertTrue(any(e["record_id"]=="revoke" and e["invalidates"] for e in index["entries"]))

    def test_aak_03_ac5_code_and_knowledge_revisions_are_independent(self):
        p=self.provider(self.OWNERS[0]); old_code=p.code_commit; old_knowledge=p.knowledge_commit
        receipt=p.index(p.commit(prepare([self.record(p.owner)],p.owner,p.collection,"op","run"),old_knowledge))
        self.assertEqual(old_code,p.code_commit); self.assertNotEqual(old_knowledge,p.knowledge_commit)
        trace=p.retrieve("next","creator-a","private-a")
        self.assertEqual(old_code,trace["input_snapshot"]["code_commit"]); self.assertEqual(receipt["target_commit"],trace["input_snapshot"]["knowledge_commit"])

if __name__=='__main__':unittest.main()
