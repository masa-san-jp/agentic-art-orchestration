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
            task['dependency_evidence'] = {}
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
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def record(self, owner, rid="r1", revision=1, lifecycle="accepted", invalidates=None):
        import hashlib
        return {"contract_version":"artifact-record/v1", "record_id":rid, "revision":revision,
          "origin_instance_id":"instance-a", "creator_id":"creator-a", "owner_repository":owner,
          "collection_id":"collection-a", "kind":"test-record", "payload_schema":"test/v1",
          "payload_ref":"payloads/"+rid+".json", "content_sha256":hashlib.sha256(b"synthetic payload").hexdigest(),
          "sources":[], "derived_from":[], "epistemic_status":"simulated", "lifecycle":lifecycle,
          "applicability":{}, "rights":{}, "access_scope":"private-a", "consent_ref":"consent-a",
          "created_at":"2026-09-05T00:00:00Z", "reviewed_at":None, "valid_until":None,
          "producer":{"kind":"test","run_id":"run-1"}, "supersedes":[], "invalidates":invalidates or []}

    def provider(self, owner, snapshot=None, creator="creator-a"):
        return LocalOwner(self.root/owner, owner, "collection-a", "a"*40, snapshot,
                          creator=creator, payload_validator=lambda r,b: r["payload_schema"] == "test/v1" and b == b"synthetic payload")

    def save(self, p, record, operation="op"):
        return p.index(p.commit(prepare([record],p.owner,p.collection,operation,"run"),
                               p.knowledge_commit, payloads={record["payload_ref"]: b"synthetic payload"}))

    def retrieve(self, p, records, creator="creator-a"):
        return p.retrieve("compare next hypothesis",creator,"private-a",at="2026-09-05T00:00:00Z",
                          decisions={p._key(r):{"decision":"adopted","reason":"explicit synthetic comparison decision",
                                               "affected":["hypothesis-2"]} for r in records})

    def test_aak_03_ac1_all_eight_git_stores_reload_receipts(self):
        import subprocess
        for owner in self.OWNERS:
            with self.subTest(owner=owner):
                p=self.provider(owner); record=self.record(owner)
                receipt=self.save(p,record)
                self.assertEqual("COMMITTED",receipt["status"])
                from tools.validate import _schema_errors, load_json
                self.assertEqual([], _schema_errors(receipt, load_json(ROOT/"schemas/knowledge-write-receipt.schema.json")))
                kind=subprocess.check_output(["git","--git-dir",str(p.git_dir),"cat-file","-t",receipt["target_commit"]],text=True).strip()
                self.assertEqual("commit",kind)
                reopened=self.provider(owner)
                self.assertEqual(receipt["target_commit"],reopened.knowledge_commit)
                trace=self.retrieve(reopened,[record])
                self.assertEqual("REUSED",trace["status"])
                self.assertEqual([], _schema_errors(trace, load_json(ROOT/"schemas/reuse-trace.schema.json")))
                self.assertEqual("instance-a",trace["records"][0]["origin_instance_id"])
                self.assertEqual(["hypothesis-2"],trace["records"][0]["affected"])

    def test_aak_03_ac2_same_operation_different_contents_conflicts(self):
        p=self.provider(self.OWNERS[0]); record=self.record(p.owner); parent=p.knowledge_commit
        bundle=prepare([record],p.owner,p.collection,"op","run")
        self.save(p,record)
        head=p._head()
        self.assertEqual("ALREADY_APPLIED",p.commit(bundle,parent)["status"])
        changed=dict(record,kind="different")
        self.assertEqual("CONFLICT",p.commit(prepare([changed],p.owner,p.collection,"op","run"),parent)["status"])
        self.assertEqual(head,p._head())
        self.assertEqual("CONFLICT",p.commit(prepare([changed],p.owner,p.collection,"op-2","run"),
                                            head,payloads={record["payload_ref"]:b"synthetic payload"})["status"])

    def test_aak_03_ac2_invalid_payload_path_revision_and_owner_are_rejected(self):
        p=self.provider(self.OWNERS[0]); base=self.record(p.owner); head=p._head()
        for field,value in [("owner_repository","wrong"),("lifecycle","candidate"),
                            ("payload_ref","../escape"),("revision",0),("payload_schema","unknown/v9"),
                            ("creator_id","creator-b")]:
            with self.subTest(field=field):
                record=dict(base);record[field]=value
                self.assertEqual("REJECTED",self.save(p,record,field)["status"])
                self.assertEqual(head,p._head())
        self.assertEqual("REJECTED",p.commit(prepare([base],p.owner,p.collection,"missing","run"),head)["status"])

    def test_aak_03_ac3_outbox_resumes_only_pending_after_reopen(self):
        from unittest.mock import patch
        owners=self.OWNERS[:2]; providers={o:self.provider(o) for o in owners}
        bundles=[prepare([self.record(o)],o,"collection-a","op-"+o,"run") for o in owners]
        payloads={o:{"payloads/r1.json":b"synthetic payload"} for o in owners}
        outbox=self.root/"outbox.json"
        first=dispatch(bundles,providers,fail_owner=owners[1],payloads=payloads,outbox=outbox)
        self.assertEqual("PARTIAL",first["status"])
        heads={o:p._head() for o,p in providers.items()}
        reopened={o:self.provider(o) for o in owners}
        with patch.object(reopened[owners[0]],"commit",side_effect=AssertionError("successful owner reexecuted")), patch.object(reopened[owners[1]],"commit",side_effect=AssertionError("committed owner reexecuted")):
            second=dispatch(bundles,reopened,payloads=payloads,outbox=outbox)
        self.assertEqual("COMMITTED",second["status"])
        self.assertEqual(heads,{o:p._head() for o,p in reopened.items()})

    def test_aak_03_ac4_new_revision_revocation_expiry_and_creator_filter(self):
        p=self.provider(self.OWNERS[0]); base=self.record(p.owner)
        self.save(p,base)
        self.assertEqual("UNAVAILABLE",self.retrieve(p,[base],creator="creator-b")["status"])
        newer=dict(base,revision=2,lifecycle="revoked")
        self.save(p,newer,"revoke")
        self.assertEqual([],self.retrieve(p,[base,newer])["records"])
        expired=dict(self.record(p.owner,"expired"),valid_until="2026-09-04T00:00:00Z")
        self.save(p,expired,"expiry")
        self.assertEqual([],self.retrieve(p,[expired])["records"])

    def test_aak_03_ac5_historical_git_snapshot_remains_reproducible(self):
        p=self.provider(self.OWNERS[0]); record=self.record(p.owner)
        first=self.save(p,record)
        self.save(p,dict(record,revision=2,lifecycle="revoked"),"revoke")
        historical=self.provider(p.owner,snapshot=first["target_commit"])
        historical.index(first)
        trace=self.retrieve(historical,[record])
        self.assertEqual("REUSED",trace["status"])
        self.assertEqual("a"*40,trace["input_snapshot"]["code_commit"])
        self.assertEqual(first["target_commit"],trace["input_snapshot"]["knowledge_commit"])

    def test_retrieval_without_explicit_use_cannot_claim_reuse(self):
        p=self.provider(self.OWNERS[0]); self.save(p,self.record(p.owner))
        self.assertEqual("NOT_APPLICABLE",p.retrieve("q","creator-a","private-a",at="2026-09-05T00:00:00Z")["status"])

    def test_reopen_as_another_creator_is_rejected(self):
        from tools.knowledge_cycle import KnowledgeCycleError
        self.provider(self.OWNERS[0])
        with self.assertRaises(KnowledgeCycleError):
            self.provider(self.OWNERS[0],creator="creator-b")

    def test_stale_parent_cannot_overwrite_other_writer(self):
        p=self.provider(self.OWNERS[0]); q=self.provider(p.owner)
        stale=q.knowledge_commit
        self.save(p,self.record(p.owner))
        head=p._head(); record=self.record(p.owner,"second")
        result=q.commit(prepare([record],q.owner,q.collection,"op-second","run"),stale,
                        payloads={record["payload_ref"]:b"synthetic payload"})
        self.assertEqual("CONFLICT",result["status"]);self.assertEqual(head,q._head())

    def test_aak_03_ac3_interruption_after_commit_before_receipt_save(self):
        from unittest.mock import patch
        p=self.provider(self.OWNERS[0]); record=self.record(p.owner)
        bundles=[prepare([record],p.owner,p.collection,"crash","run")]
        outbox=self.root/"outbox.json"
        with patch.object(p,"index",side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                dispatch(bundles,{p.owner:p},outbox=outbox,
                         payloads={p.owner:{record["payload_ref"]:b"synthetic payload"}})
        committed=p._head()
        reopened=self.provider(p.owner)
        report=dispatch(bundles,{p.owner:reopened},outbox=outbox)
        self.assertEqual("COMMITTED",report["status"])
        self.assertEqual(committed,reopened._head())

    def test_aak_03_ac4_source_revocation_enumerates_dependent_revision(self):
        p=self.provider(self.OWNERS[0]); source=self.record(p.owner,"source")
        self.save(p,source,"source")
        derived=self.record(p.owner,"derived")
        derived["derived_from"]=[{"record_id":"source","revision":1}]
        self.save(p,derived,"derived")
        revocation=self.record(p.owner,"revocation",invalidates=[{"record_id":"source","revision":1}])
        self.save(p,revocation,"revocation")
        index=json.loads(p.index_path.read_bytes())
        self.assertEqual(["derived"],[r["record_id"] for r in index["revalidation_candidates"]])
        self.assertEqual([],self.retrieve(p,[source,derived])["records"])

    def test_operational_owner_cli_git_reload_and_index(self):
        import subprocess
        import sys
        import hashlib
        from tools.knowledge_cycle import canonical
        owner="agentic-art-orchestration"
        record=self.record(owner)
        payload=canonical({"contract_version":"operational-knowledge/v1",
                           "failure_kind":"interruption","observation":"synthetic interrupted index",
                           "recovery_proposal":"Rebuild index from accepted commit",
                           "verification_refs":["fixture:restart-1"],"changes_authority":False})
        record.update(payload_schema="operational-knowledge/v1",
                      content_sha256=hashlib.sha256(payload).hexdigest())
        source=self.root/"input";(source/"payloads").mkdir(parents=True)
        (source/"payloads/r1.json").write_bytes(payload)
        record_path=self.root/"record.json";record_path.write_bytes(canonical(record))
        command=[sys.executable,str(ROOT/"tools/knowledge_cycle.py")]
        common=["--store",str(self.root/"store"),"--owner",owner,"--creator","creator-a",
                "--collection","collection-a","--code-commit","a"*40]
        initialized=json.loads(subprocess.check_output(command+["init"]+common))
        receipt=json.loads(subprocess.check_output(command+["commit"]+common+
                          ["--record",str(record_path),"--payload-root",str(source),
                           "--operation-id","cli-op","--run-id","cli-run",
                           "--knowledge-commit",initialized["knowledge_commit"]]))
        self.assertEqual("COMMITTED",receipt["status"])
        receipt_path=self.root/"receipt.json";receipt_path.write_bytes(canonical(receipt))
        indexed=json.loads(subprocess.check_output(command+["index"]+common+["--receipt",str(receipt_path)]))
        self.assertEqual(receipt["target_commit"],indexed["index_commit"])

    def test_cyclic_generated_source_is_rejected(self):
        p=self.provider(self.OWNERS[0]); record=self.record(p.owner)
        record["derived_from"]=[{"record_id":"r1","revision":1}]
        head=p._head()
        self.assertEqual("REJECTED",self.save(p,record)["status"])
        self.assertEqual(head,p._head())

    def test_owner_exception_keeps_other_owner_success(self):
        from unittest.mock import patch
        owners=self.OWNERS[:2];providers={o:self.provider(o) for o in owners}
        bundles=[prepare([self.record(o)],o,"collection-a",o,"run") for o in owners]
        with patch.object(providers[owners[0]],"commit",side_effect=RuntimeError("synthetic failure")):
            result=dispatch(bundles,providers,payloads={o:{"payloads/r1.json":b"synthetic payload"} for o in owners})
        self.assertEqual("PARTIAL",result["status"])
        self.assertEqual("COMMITTED",result["receipts"][1]["status"])

    def test_parent_dispatch_does_not_write_public_catalog(self):
        from unittest.mock import patch
        p=self.provider("agentic-art-project")
        head=p._head()
        bundle=prepare([self.record(p.owner)],p.owner,p.collection,"catalog","run")
        with patch.object(p,"commit",side_effect=AssertionError("catalog write attempted")):
            result=dispatch([bundle],{p.owner:p})
        self.assertEqual("REJECTED",result["receipts"][0]["status"])
        self.assertEqual(head,p._head())

if __name__=='__main__':unittest.main()
