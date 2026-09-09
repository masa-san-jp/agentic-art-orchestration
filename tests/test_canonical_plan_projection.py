"""Projection transaction regression tests; owner-boundary stubs are not live proof."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml

from tests import test_public_projection as regression
from tests.test_public_projection import synthetic_owner_boundary
from tools import public_projection as p
from tools.canonical_plan_projection import _owner_bundle


class CanonicalPlanProjectionTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.helper=regression.PublicProjectionContractTests();self.helper.setUp()
        self.target=self.helper._new_target(self.root);p.init_target(self.target,apply=True)
        self.helper._git(self.target,'add','.');self.helper._git(self.target,'commit','-m','synthetic scaffold')
        self.report=self.helper._automatic_report(self.root)

    def project(self, **kwargs):
        return p.project_plan_automatic(self.report,internal_output_root=self.root/'internal',public_projection_root=self.target,state_root=self.root/'state',**kwargs)

    def test_owner_validator_uses_selected_child_interpreter(self):
        """A pinned child checkout may have no repo-local .venv."""
        with tempfile.TemporaryDirectory(prefix="owner-python-") as temporary:
            root = Path(temporary).resolve()
            code = root / "production-code"
            code.mkdir()
            internal = root / "internal"
            project = internal / "production" / "demo"
            plan = project / "03_plan" / "production-plan.md"
            plan.parent.mkdir(parents=True)
            body = b"# Demo plan\n"
            plan.write_bytes(body)
            commit = "a" * 40
            attestation = {
                "project_id": "demo",
                "plan_id": "PL001",
                "plan_revision": 1,
                "producer": {"commit": commit, "repository": "masa-san-jp/agentic-art-production"},
                "human_plan": {"sha256": "sha256:" + hashlib.sha256(body).hexdigest()},
                "assets": [],
            }
            attestation_path = plan.with_name("public-plan-attestation.json")
            attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
            item = {
                "plan": str(plan),
                "production_code_root": str(code),
                "production_source_commit": commit,
                "production_plan_markdown_sha256": hashlib.sha256(body).hexdigest(),
                "public_plan_attestation": str(attestation_path),
                "public_plan_attestation_sha256": hashlib.sha256(attestation_path.read_bytes()).hexdigest(),
                "source_identity": "demo#PL001",
                "plan_revision": 1,
            }
            with patch("tools.canonical_plan_projection.subprocess.check_output", side_effect=[commit + "\n", ""]), \
                    patch("tools.canonical_plan_projection.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    ["selected-python"], 0,
                    stdout=json.dumps({"status": "VERIFIED", "production_state": "PLANNING"}),
                    stderr="",
                )
                result = _owner_bundle(item, internal, child_python="selected-python")

        self.assertEqual("demo#PL001", result["identity"])
        command = run.call_args.args[0]
        self.assertEqual("selected-python", command[0])
        self.assertEqual("tools/public_plan_attestation.py", command[1])

    def next_run(self, suffix):
        self.report['run_id']='RUN-REVISION-'+suffix
        self.report['destination_resolution']=self.helper._profile_resolution(self.root,self.report['run_id'],public=True)
        self.report['automatic_plan_authority']=p.build_automatic_plan_authority(producer='tools/run.py',source_status='PLAN_READY',source_id=self.report['run_id'],source_sha256=self.report['production_plan_sha256'],destination_resolution=self.report['destination_resolution'])

    def test_unattested_summary_rejected_by_actual_owner_boundary_without_writes(self):
        before=p._tree_fingerprint(self.target)
        result=self.project()
        self.assertEqual('BLOCKED_POLICY',result['status']);self.assertEqual(before,p._tree_fingerprint(self.target))

    @unittest.skipUnless(os.environ.get('AAK_PRODUCTION_CODE_ROOT'), 'requires explicit qualified Production checkout')
    def test_actual_production_validator_exact_bytes_and_tamper(self):
        from tools.canonical_plan_projection import source_fields
        code=Path(os.environ['AAK_PRODUCTION_CODE_ROOT']).resolve()
        destination=self.root/'internal/production/attestation'
        script='''import pathlib, shutil, sys
from tests.test_public_plan_attestation import PublicPlanAttestationTests
from tools.public_plan_attestation import write_attestation
t=PublicPlanAttestationTests(); t.setUp()
try:
    write_attestation(t.project/'03_plan/public-plan-attestation.json', t.attest())
    shutil.copytree(t.project, pathlib.Path(sys.argv[1]))
finally:
    t.doCleanups()
'''
        subprocess.run([str(code/'.venv/bin/python'), '-c', script, str(destination)], cwd=code, check=True, capture_output=True)
        plan=destination/'03_plan/production-plan.md'
        self.report.update(source_fields(plan,code))
        self.report['production_source_commit']=subprocess.check_output(['git','-C',str(code),'rev-parse','HEAD'],text=True).strip()
        self.report['production_plan_sha256']=p._sha256_bytes(plan.read_bytes())
        self.next_run('ACTUAL')
        result=self.project()
        self.assertEqual('APPLIED',result['status'],result)
        record=next((self.target/'plans').glob('P0001-*'))
        receiver=os.environ.get('AAK_PROJECT_CODE_ROOT')
        if receiver:
            # Exercise the receiver's native flat YAML readers, not PyYAML,
            # which accepts continuation lines the public catalog cannot read.
            script='''from pathlib import Path
import sys
from tools.attestation_receiver import check_envelope
from tools.validate import mapping_fields
from tools.catalog_sync import _parse_list_records
record=Path(sys.argv[1])
metadata=mapping_fields(record/'metadata.yaml')
entry=_parse_list_records(record.parent/'index.yaml', 'records')[0]
check_envelope(record, metadata, entry)
'''
            received = subprocess.run(['python3','-c',script,str(record)],cwd=receiver,capture_output=True,text=True)
            self.assertEqual(0, received.returncode, received.stderr)
        for path in (destination/'03_plan').rglob('*'):
            if path.is_file() and (path.name in {'production-plan.md','public-plan-attestation.json'} or 'media' in path.parts):
                relative='plan.md' if path.name=='production-plan.md' else path.relative_to(destination/'03_plan')
                self.assertEqual(path.read_bytes(),(record/relative).read_bytes())
        self.assertEqual('ALREADY_PROJECTED', self.project()['status'])
        attestation=plan.with_name('public-plan-attestation.json')
        original_body=plan.read_bytes();original_attestation=attestation.read_bytes()
        attested=json.loads(original_attestation);asset=destination/attested['assets'][0]['path'];original_asset=asset.read_bytes()
        valid_report=copy.deepcopy(self.report)
        for case in ('SUMMARY','IMITATION','BODY','ATTESTATION','MISSING','ASSET','RIGHTS','HASH'):
            self.report=copy.deepcopy(valid_report)
            plan.write_bytes(original_body);attestation.write_bytes(original_attestation);asset.write_bytes(original_asset)
            if case=='SUMMARY':plan.write_bytes(b'# Summary\n')
            if case=='IMITATION':plan.write_bytes(b'# Integrated plan\n## Scope\n## Budget\n')
            if case=='BODY':plan.write_bytes(original_body+b' ')
            if case=='ATTESTATION':attestation.write_bytes(original_attestation+b' ')
            if case=='MISSING':attestation.unlink()
            if case=='ASSET':asset.unlink()
            if case=='RIGHTS':
                altered=copy.deepcopy(attested);altered['publication_review']['rights']='UNKNOWN'
                attestation.write_text(json.dumps(altered))
            self.report['production_plan_sha256']=p._sha256_bytes(plan.read_bytes()) if case!='HASH' else '0'*64
            # Do not repair forged envelope integrity or grant public consent.
            if case=='RIGHTS':self.report['public_plan_attestation_sha256']=p._sha256_bytes(attestation.read_bytes())
            self.next_run(case)
            before=p._tree_fingerprint(self.target)
            with self.subTest(case=case):
                self.assertEqual('BLOCKED_POLICY',self.project()['status'])
                self.assertEqual(before,p._tree_fingerprint(self.target))

    @patch('tools.canonical_plan_projection._owner_bundle',synthetic_owner_boundary)
    def test_same_identity_revision_conflict_and_higher_revision_preserve_public_id(self):
        self.assertEqual('APPLIED',self.project()['status'])
        plan=Path(self.report['plan']);plan.write_bytes(plan.read_bytes()+b'\nNew version\n')
        self.report['production_plan_sha256']=p._sha256_bytes(plan.read_bytes())
        self.next_run('CONFLICT')
        before=p._tree_fingerprint(self.target)
        self.assertEqual('BLOCKED_CONFLICT',self.project()['status']);self.assertEqual(before,p._tree_fingerprint(self.target))
        self.report['plan_revision']=2
        self.next_run('TWO')
        result=self.project();self.assertEqual('APPLIED',result['status']);self.assertEqual(['P0001'],result['public_ids'])
        index=yaml.safe_load((self.target/'plans/index.yaml').read_text());self.assertEqual('2',index['records'][0]['plan_revision'])
        self.report['plan_revision']=1
        self.next_run('ROLLBACK')
        self.assertEqual('BLOCKED_CONFLICT',self.project()['status'])

    @patch('tools.canonical_plan_projection._owner_bundle',synthetic_owner_boundary)
    def test_high_revision_failure_restores_prior_body_and_catalog(self):
        self.project();before=p._tree_fingerprint(self.target)
        self.report['plan_revision']=2
        self.next_run('INJECTED')
        result=self.project(fail_after=1)
        self.assertEqual('FAILED',result['status']);self.assertEqual(before,p._tree_fingerprint(self.target))
        self.assertEqual([],result['changed_paths'])

    @patch('tools.canonical_plan_projection._owner_bundle',synthetic_owner_boundary)
    def test_reused_run_id_preserves_original_receipt_and_target(self):
        self.project()
        receipt=self.root/'state'/self.report['run_id']/'public-projection-result.json'
        original=receipt.read_bytes();before=p._tree_fingerprint(self.target)
        self.report['plan_revision']=2
        self.assertEqual('BLOCKED_CONFLICT',self.project()['status'])
        self.assertEqual(original,receipt.read_bytes());self.assertEqual(before,p._tree_fingerprint(self.target))

    def test_obsolete_asset_removal_rolls_back_then_applies_exactly(self):
        asset=self.target/'plans/obsolete.svg';asset.write_bytes(b'old reviewed asset')
        before=p._tree_fingerprint(self.target)
        result=p._apply_projection_transaction(self.target,before=before,planned_files={},target_updates={},target_removals={'plans/obsolete.svg':asset.read_bytes()},fail_after=1)
        self.assertEqual('FAILED',result['outcome']);self.assertEqual(before,p._tree_fingerprint(self.target))
        result=p._apply_projection_transaction(self.target,before=before,planned_files={},target_updates={},target_removals={'plans/obsolete.svg':asset.read_bytes()})
        self.assertEqual('APPLIED',result['outcome']);self.assertFalse(asset.exists())

    @patch('tools.canonical_plan_projection._owner_bundle',synthetic_owner_boundary)
    def test_reserved_migration_id_and_unrelated_dirty_file_are_preserved(self):
        (self.target/'plans/migration.yaml').write_text('version: 1\nrecords:\n  - id: P0008\n    source_candidate: unknown\n    blocking_reason: absent\n    unblock_condition: owner-proof\n')
        self.helper._git(self.target,'add','.');self.helper._git(self.target,'commit','-m','synthetic reservation')
        (self.target/'unrelated.txt').write_text('preserve')
        before=p._tree_fingerprint(self.target)
        self.assertEqual('BLOCKED_CONFLICT',self.project()['status']);self.assertEqual(before,p._tree_fingerprint(self.target))
        self.helper._git(self.target,'add','.');self.helper._git(self.target,'commit','-m','synthetic unrelated file')
        self.assertEqual(['P0009'],self.project()['public_ids'])
