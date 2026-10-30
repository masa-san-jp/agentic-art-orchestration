"""Projection transaction regression tests; owner-boundary stubs are not live proof."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

from tests import test_public_projection as regression
from tests.test_public_projection import synthetic_owner_boundary
from tools import public_projection as p
from tools.canonical_plan_projection import _owner_bundle, ensure_automatic_attestation


FAKE_ATTESTATION_TOOL = '''"""Fake Production attestation CLI: logs argv; a `reject` file rejects.

Files in 03_plan/media are attested as assets. A `check-fail` file makes --check reject; a `hang` file makes every call sleep past a short timeout.
"""
import hashlib, json, pathlib, sys, time
args = sys.argv[1:]
code = pathlib.Path(__file__).resolve().parents[1]
with (code / "calls.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
if (code / "hang").exists():
    time.sleep(float((code / "hang").read_text() or "5"))
if (code / "reject").exists():
    print(json.dumps({"status": "REJECTED", "reason": (code / "reject").read_text().strip()})); sys.exit(1)
project = pathlib.Path(args[args.index("--project-root") + 1])
path = project / "03_plan/public-plan-attestation.json"
body = "sha256:" + hashlib.sha256((project / "03_plan/production-plan.md").read_bytes()).hexdigest()
media = project / "03_plan/media"
assets = [{"path": "03_plan/media/" + item.name, "sha256": "sha256:" + hashlib.sha256(item.read_bytes()).hexdigest()}
          for item in sorted(media.iterdir()) if item.is_file()] if media.is_dir() else []
if "--check" in args:
    current = json.loads(path.read_text())
    ok = current["human_plan"]["sha256"] == body and current["assets"] == assets and not (code / "check-fail").exists()
    print(json.dumps({"status": "VERIFIED", "production_state": "PLANNING"} if ok else {"status": "REJECTED"}))
    sys.exit(0 if ok else 1)
document = {"project_id": project.name, "plan_id": "PL001", "plan_revision": 1,
            "generated_at": args[args.index("--generated-at") + 1], "human_plan": {"sha256": body}, "assets": assets,
            "producer": {"repository": "masa-san-jp/agentic-art-production", "commit": args[args.index("--producer-commit") + 1]}}
data = json.dumps(document, sort_keys=True) + "\\n"
if path.exists() and path.read_text() != data:
    print(json.dumps({"status": "REJECTED", "reason": "ATTESTATION_CONFLICT"})); sys.exit(1)
path.write_text(data)
print(json.dumps({"status": "ATTESTED"}))
'''


def write_fake_attestation_tool(code):
    """Install the fake owner CLI below `code`; it writes like the real one (create-only)."""
    tool = Path(code) / "tools" / "public_plan_attestation.py"
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text(FAKE_ATTESTATION_TOOL, encoding="utf-8")
    return tool


class AutomaticAttestationTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.root = Path(t.name)
        self.code = self.root / "production-code"
        write_fake_attestation_tool(self.code)
        self.project = self.root / "internal" / "production" / "demo"
        (self.project / "03_plan").mkdir(parents=True)
        (self.project / "03_plan/production-plan.md").write_bytes(b"# Demo plan\n")

    def attest(self, clock, commit="a" * 40, **kwargs):
        return ensure_automatic_attestation(python=sys.executable, code=self.code, project=self.project,
                                            producer_commit=commit, generated_at=clock, **kwargs)

    def superseded(self):
        return self.root / "state" / "superseded-attestations"

    def calls(self):
        return [json.loads(line) for line in (self.code / "calls.jsonl").read_text().splitlines()]

    def test_resume_with_a_verified_attestation_for_the_same_bytes_does_not_regenerate(self):
        self.assertEqual("ATTESTED", self.attest("2026-10-27T00:00:00Z")["status"])
        self.assertEqual("ALREADY_ATTESTED", self.attest("2026-10-28T00:00:00Z")["status"])
        self.assertEqual([True, False], ["--automatic-plan" in call for call in self.calls()])

    def test_owner_rejection_is_returned_as_its_finding(self):
        (self.code / "reject").write_text("PUBLIC_URL_BLOCKED\n", encoding="utf-8")
        result = self.attest("2026-10-27T00:00:00Z")
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual({"status": "REJECTED", "reason": "PUBLIC_URL_BLOCKED"}, result["finding"])
        self.assertEqual("--automatic-plan", result["command"][4])
        self.assertEqual(1, len(self.calls()))

    def _assert_retired(self, result, old_bytes, reason):
        retired = result["retired"]
        self.assertEqual(reason, retired["reason"])
        self.assertEqual(hashlib.sha256(old_bytes).hexdigest(), retired["sha256"])
        kept = Path(retired["path"])
        self.assertEqual(self.superseded() / "demo", kept.parent)
        self.assertEqual(old_bytes, kept.read_bytes())

    def test_changed_plan_bytes_retire_the_stale_attestation_and_reattest(self):
        self.attest("2026-10-27T00:00:00Z")
        attestation = self.project / "03_plan/public-plan-attestation.json"
        old = attestation.read_bytes()
        (self.project / "03_plan/production-plan.md").write_bytes(b"# Changed plan\n")
        result = self.attest("2026-10-28T00:00:00Z", superseded_root=self.superseded())
        self.assertEqual("REATTESTED", result["status"])
        self._assert_retired(result, old, "PLAN_BYTES_CHANGED")
        new = json.loads(attestation.read_text())
        self.assertEqual("sha256:" + hashlib.sha256(b"# Changed plan\n").hexdigest(), new["human_plan"]["sha256"])
        self.assertEqual("2026-10-28T00:00:00Z", new["generated_at"])
        # Stale bytes need no --check: the owner CLI only generated twice.
        self.assertEqual([True, True], ["--automatic-plan" in call for call in self.calls()])
        # The plan itself is never touched.
        self.assertEqual(b"# Changed plan\n", (self.project / "03_plan/production-plan.md").read_bytes())

    def test_changed_plan_bytes_without_a_superseded_root_name_the_stale_attestation(self):
        self.attest("2026-10-27T00:00:00Z")
        attestation = self.project / "03_plan/public-plan-attestation.json"
        old = attestation.read_bytes()
        (self.project / "03_plan/production-plan.md").write_bytes(b"# Changed plan\n")
        result = self.attest("2026-10-28T00:00:00Z")
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual({"status": "REJECTED", "reason": "ATTESTATION_STALE: PLAN_BYTES_CHANGED"}, result["finding"])
        self.assertEqual(old, attestation.read_bytes())
        self.assertEqual(1, len(self.calls()))

    def test_existing_attestation_for_another_producer_commit_is_reattested(self):
        self.attest("2026-10-27T00:00:00Z", commit="a" * 40)
        attestation = self.project / "03_plan/public-plan-attestation.json"
        old = attestation.read_bytes()
        result = self.attest("2026-10-28T00:00:00Z", commit="b" * 40, superseded_root=self.superseded())
        self.assertEqual("REATTESTED", result["status"])
        self._assert_retired(result, old, "PRODUCER_COMMIT_CHANGED")
        self.assertEqual("b" * 40, json.loads(attestation.read_text())["producer"]["commit"])
        self.assertEqual([True, True], ["--automatic-plan" in call for call in self.calls()])

    def test_existing_attestation_that_fails_the_owner_check_is_reattested(self):
        self.attest("2026-10-27T00:00:00Z")
        attestation = self.project / "03_plan/public-plan-attestation.json"
        old = attestation.read_bytes()
        (self.code / "check-fail").write_text("", encoding="utf-8")
        result = self.attest("2026-10-28T00:00:00Z", superseded_root=self.superseded())
        self.assertEqual("REATTESTED", result["status"])
        self._assert_retired(result, old, "CHECK_FAILED")
        self.assertEqual(["--automatic-plan", "--check", "--automatic-plan"],
                         [call[2] for call in self.calls()])
        self.assertNotEqual(old, attestation.read_bytes())

    def test_retiring_the_same_stale_bytes_twice_keeps_one_copy(self):
        attestation = self.project / "03_plan/public-plan-attestation.json"
        self.attest("2026-10-27T00:00:00Z")
        old = attestation.read_bytes()
        (self.project / "03_plan/production-plan.md").write_bytes(b"# Changed plan\n")
        first = self.attest("2026-10-28T00:00:00Z", superseded_root=self.superseded())
        # Something put the identical stale bytes back; retiring them again is harmless.
        attestation.write_bytes(old)
        second = self.attest("2026-10-28T00:00:00Z", superseded_root=self.superseded())
        self.assertEqual(first["retired"]["path"], second["retired"]["path"])
        self.assertEqual(1, len(list((self.superseded() / "demo").iterdir())))
        self.assertEqual("REATTESTED", second["status"])

    def test_timeouts_are_retried_with_backoff_then_reported_unavailable(self):
        waits = []
        timeout = subprocess.TimeoutExpired(["python"], 120)
        with patch("tools.canonical_plan_projection.subprocess.run", side_effect=timeout) as run:
            result = self.attest("2026-10-27T00:00:00Z", sleep=waits.append)
        self.assertEqual(3, run.call_count)
        self.assertEqual([1, 2], waits)
        self.assertEqual("UNAVAILABLE", result["status"])
        self.assertEqual(3, result["attempts"])
        self.assertEqual("UNAVAILABLE", result["finding"]["status"])
        self.assertTrue(result["finding"]["reason"].startswith("TimeoutExpired: "))
        self.assertIn("--automatic-plan", result["command"])

    def test_os_error_is_retried_and_a_later_answer_is_used(self):
        waits = []
        real = subprocess.run
        outcomes = [OSError("busy"), None]

        def flaky(*args, **kwargs):
            outcome = outcomes.pop(0)
            if outcome is not None:
                raise outcome
            return real(*args, **kwargs)

        with patch("tools.canonical_plan_projection.subprocess.run", side_effect=flaky):
            result = self.attest("2026-10-27T00:00:00Z", sleep=waits.append)
        self.assertEqual("ATTESTED", result["status"])
        self.assertEqual([1], waits)
        self.assertEqual(1, len(self.calls()))

    def test_os_error_on_every_attempt_is_reported_unavailable(self):
        with patch("tools.canonical_plan_projection.subprocess.run", side_effect=OSError("no interpreter")):
            result = self.attest("2026-10-27T00:00:00Z", sleep=lambda seconds: None)
        self.assertEqual("UNAVAILABLE", result["status"])
        self.assertTrue(result["finding"]["reason"].startswith("OSError: "))

    def test_a_timed_out_check_is_retried_before_it_is_trusted(self):
        self.attest("2026-10-27T00:00:00Z")
        real = subprocess.run
        outcomes = [subprocess.TimeoutExpired(["python"], 120), None]

        def flaky(*args, **kwargs):
            outcome = outcomes.pop(0)
            if outcome is not None:
                raise outcome
            return real(*args, **kwargs)

        with patch("tools.canonical_plan_projection.subprocess.run", side_effect=flaky):
            result = self.attest("2026-10-28T00:00:00Z", sleep=lambda seconds: None)
        self.assertEqual("ALREADY_ATTESTED", result["status"])

    def publish(self, body=b"# Demo plan\n", revision="1"):
        """A receiver that already holds demo#PL001 at `revision` for `body`, with the current
        internal attestation and media copied into the record as a projection would."""
        public = self.root / "public"
        record = public / "plans/P0001-demo"
        record.mkdir(parents=True, exist_ok=True)
        (record / "plan.md").write_bytes(body)
        attestation = (self.project / "03_plan/public-plan-attestation.json").read_bytes()
        (record / "public-plan-attestation.json").write_bytes(attestation)
        media = self.project / "03_plan/media"
        for item in sorted(media.iterdir()) if media.is_dir() else []:
            (record / "media").mkdir(exist_ok=True)
            (record / "media" / item.name).write_bytes(item.read_bytes())
        (public / "plans/index.yaml").write_text(yaml.safe_dump({"version": 1, "retired_ids": [], "records": [{
            "id": "P0001", "slug": "demo", "path": "plans/P0001-demo", "source_identity": "demo#PL001",
            "plan_revision": revision, "content_sha256": hashlib.sha256(body).hexdigest(),
            "attestation_sha256": hashlib.sha256(attestation).hexdigest(), "production_commit": "a" * 40}]}),
            encoding="utf-8")
        return public

    def test_published_bytes_with_changed_media_are_reattested_not_already_published(self):
        """Identical plan.md is not enough: a re-rendered medium is new attested content."""
        media = self.project / "03_plan/media"
        media.mkdir()
        (media / "figure.svg").write_bytes(b"<svg>old</svg>\n")
        self.attest("2026-10-27T00:00:00Z", commit="a" * 40)
        public = self.publish()
        (media / "figure.svg").write_bytes(b"<svg>new</svg>\n")
        result = self.attest("2026-10-28T00:00:00Z", commit="b" * 40, superseded_root=self.superseded(),
                             public_projection_root=public)
        self.assertEqual("REATTESTED", result["status"])
        self.assertEqual("PRODUCER_COMMIT_CHANGED", result["retired"]["reason"])
        new = json.loads((self.project / "03_plan/public-plan-attestation.json").read_text())
        self.assertEqual("sha256:" + hashlib.sha256(b"<svg>new</svg>\n").hexdigest(), new["assets"][0]["sha256"])
        self.assertEqual("b" * 40, new["producer"]["commit"])

    def test_published_bytes_and_media_after_a_commit_change_are_already_published(self):
        media = self.project / "03_plan/media"
        media.mkdir()
        (media / "figure.svg").write_bytes(b"<svg>same</svg>\n")
        self.attest("2026-10-27T00:00:00Z", commit="a" * 40)
        result = self.attest("2026-10-28T00:00:00Z", commit="b" * 40, superseded_root=self.superseded(),
                             public_projection_root=self.publish())
        self.assertEqual("ALREADY_PUBLISHED", result["status"])

    def test_retirement_copies_inside_the_destination_directory_before_unlinking(self):
        """A rename never crosses directories (or filesystems); the copy is verified first."""
        from tools import canonical_plan_projection as module
        self.attest("2026-10-27T00:00:00Z")
        attestation = self.project / "03_plan/public-plan-attestation.json"
        old = attestation.read_bytes()
        (self.project / "03_plan/production-plan.md").write_bytes(b"# Changed plan\n")
        renames, real_replace = [], os.replace

        def replace(source, destination):
            renames.append((Path(source), Path(destination)))
            self.assertTrue(attestation.exists(), "the original is kept until the copy is in place")
            return real_replace(source, destination)

        with patch.object(module.os, "replace", side_effect=replace):
            result = self.attest("2026-10-28T00:00:00Z", superseded_root=self.superseded())
        self.assertEqual("REATTESTED", result["status"])
        (source, destination), = renames
        self.assertEqual(destination.parent, source.parent)
        self.assertEqual(old, destination.read_bytes())
        self.assertEqual([destination], list((self.superseded() / "demo").iterdir()))

    def test_an_unverified_copy_keeps_the_original_and_reports_the_retirement_failure(self):
        from tools import canonical_plan_projection as module
        self.attest("2026-10-27T00:00:00Z")
        attestation = self.project / "03_plan/public-plan-attestation.json"
        old = attestation.read_bytes()
        (self.project / "03_plan/production-plan.md").write_bytes(b"# Changed plan\n")
        with patch.object(module, "_kept_copy_matches", return_value=False):
            result = self.attest("2026-10-28T00:00:00Z", superseded_root=self.superseded())
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("ATTESTATION_RETIRE_FAILED: OSError", result["finding"]["reason"])
        self.assertEqual(old, attestation.read_bytes())
        self.assertEqual([], [path for path in (self.superseded() / "demo").iterdir() if path.name.endswith(".tmp")])

    def test_an_attestation_changed_during_retirement_is_not_unlinked(self):
        from tools import canonical_plan_projection as module
        self.attest("2026-10-27T00:00:00Z")
        attestation = self.project / "03_plan/public-plan-attestation.json"
        (self.project / "03_plan/production-plan.md").write_bytes(b"# Changed plan\n")
        real_replace = os.replace

        def replace_then_change(source, destination):
            real_replace(source, destination)
            attestation.write_bytes(b'{"changed": true}\n')

        with patch.object(module.os, "replace", side_effect=replace_then_change):
            result = self.attest("2026-10-28T00:00:00Z", superseded_root=self.superseded())
        self.assertEqual("ATTESTATION_RETIRE_FAILED: OSError", result["finding"]["reason"])
        self.assertEqual(b'{"changed": true}\n', attestation.read_bytes())

    def test_only_the_producer_commit_changed_for_published_bytes_is_not_reattested(self):
        self.attest("2026-10-27T00:00:00Z", commit="a" * 40)
        attestation = self.project / "03_plan/public-plan-attestation.json"
        old = attestation.read_bytes()
        result = self.attest("2026-10-28T00:00:00Z", commit="b" * 40, superseded_root=self.superseded(),
                             public_projection_root=self.publish())
        self.assertEqual("ALREADY_PUBLISHED", result["status"])
        self.assertEqual("P0001", result["public_record"])
        self.assertNotIn("retired", result)
        self.assertEqual(old, attestation.read_bytes())
        self.assertFalse(self.superseded().exists())
        self.assertEqual(1, len(self.calls()))

    def test_changed_bytes_are_reattested_even_when_an_older_body_is_published(self):
        self.attest("2026-10-27T00:00:00Z", commit="a" * 40)
        public = self.publish()
        (self.project / "03_plan/production-plan.md").write_bytes(b"# Changed plan\n")
        result = self.attest("2026-10-28T00:00:00Z", commit="b" * 40, superseded_root=self.superseded(),
                             public_projection_root=public)
        self.assertEqual("REATTESTED", result["status"])
        self.assertEqual("PLAN_BYTES_CHANGED", result["retired"]["reason"])

    def test_relative_code_and_project_paths_are_resolved(self):
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.root)
        result = ensure_automatic_attestation(
            python=sys.executable, code=Path("production-code"), project=Path("internal/production/demo"),
            producer_commit="a" * 40, generated_at="2026-10-27T00:00:00Z")
        self.assertEqual("ATTESTED", result["status"])
        self.assertTrue(Path(result["command"][1]).is_absolute())
        project = Path(result["command"][result["command"].index("--project-root") + 1])
        self.assertEqual(self.project.resolve(), project)
        self.assertTrue((self.project / "03_plan/public-plan-attestation.json").is_file())


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

    @patch('tools.canonical_plan_projection._owner_bundle', synthetic_owner_boundary)
    def test_automatic_plan_projection_binds_project_introduction_to_canonical_revision(self):
        result = self.project()
        self.assertEqual('APPLIED', result['status'])
        record = next((self.target / 'plans').glob('P0001-*'))
        readme = (record / 'README.md').read_bytes()
        metadata = yaml.safe_load((record / 'metadata.yaml').read_text(encoding='utf-8'))
        index = yaml.safe_load((self.target / 'plans/index.yaml').read_text(encoding='utf-8'))['records'][0]
        self.assertEqual('project-plan-introduction/v1', metadata['introduction_contract'])
        self.assertEqual('1', metadata['introduction_revision'])
        self.assertEqual(hashlib.sha256(readme).hexdigest(), metadata['introduction_sha256'])
        self.assertEqual(metadata['introduction_sha256'], index['introduction_sha256'])
        for heading in ('作品体験', '主張', '発想の由来', '素材・形式', '制作入口'):
            self.assertIn(f'## {heading}'.encode('utf-8'), readme)
        self.assertEqual(self.report['production_plan_sha256'], hashlib.sha256((record / 'plan.md').read_bytes()).hexdigest())
        self.assertEqual([], p.validate_result(json.loads((self.root / 'state' / self.report['run_id'] / 'public-projection-result.json').read_text())))

    @patch('tools.canonical_plan_projection._owner_bundle', synthetic_owner_boundary)
    def test_resume_after_the_project_regenerated_its_lineage_index_is_already_projected(self):
        self.assertEqual('APPLIED', self.project()['status'])
        # tools/run.py runs the Project's catalog generator after a projection.
        (self.target / 'plans/lineage-index.json').write_text('{"records":[]}\n', encoding='utf-8')
        self.assertEqual('ALREADY_PROJECTED', self.project()['status'])
        (self.target / 'plans/unrelated.txt').write_text('x\n', encoding='utf-8')
        self.assertEqual('BLOCKED_CONFLICT', self.project()['status'])

    def next_run(self, suffix):
        self.report['run_id']='RUN-REVISION-'+suffix
        self.report['destination_resolution']=self.helper._profile_resolution(self.root,self.report['run_id'],public=True)
        self.report['automatic_plan_authority']=p.build_automatic_plan_authority(producer='tools/run.py',source_status='PLAN_READY',source_id=self.report['run_id'],source_sha256=self.report['production_plan_sha256'],destination_resolution=self.report['destination_resolution'])

    def test_unattested_summary_rejected_by_actual_owner_boundary_without_writes(self):
        before=p._tree_fingerprint(self.target)
        result=self.project()
        self.assertEqual('BLOCKED_POLICY',result['status']);self.assertEqual(before,p._tree_fingerprint(self.target))
        finding=json.loads((self.root/'state'/self.report['run_id']/'public-projection-result.json').read_text())['findings'][0]
        self.assertIn('reason: ',finding['remediation']);self.assertNotIn(str(self.root),finding['remediation'])

    @patch('tools.canonical_plan_projection._owner_bundle',synthetic_owner_boundary)
    def test_finding_keeps_the_fixed_reason_for_a_receiver_index_without_retired_ids(self):
        index_path=self.target/'plans/index.yaml'
        index=yaml.safe_load(index_path.read_text());del index['retired_ids']
        index_path.write_text(yaml.safe_dump(index))
        result=self.project()
        self.assertEqual('BLOCKED_POLICY',result['status']);self.assertEqual(['FORBIDDEN_CONTENT'],result['finding_codes'])
        evidence=json.loads((self.root/'state'/self.report['run_id']/'public-projection-result.json').read_text())
        self.assertTrue(evidence['findings'][0]['remediation'].endswith('reason: receiver index contract required'))
        self.assertEqual([],p.validate_result(evidence))

    def test_reason_from_outside_this_module_is_reduced_to_its_type(self):
        from tools.canonical_plan_projection import _failure_reason
        try:
            json.loads('{"secret": /private/path')
        except ValueError as exc:
            self.assertEqual('JSONDecodeError',_failure_reason(exc))
        self.assertEqual('OSError',_failure_reason(OSError('/private/path')))

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

    def test_identical_bytes_after_a_producer_commit_change_are_already_projected(self):
        """Only the commit changed: keep the record and its public attestation, write nothing."""
        with patch('tools.canonical_plan_projection._owner_bundle', synthetic_owner_boundary):
            self.assertEqual('APPLIED', self.project()['status'])
        record = yaml.safe_load((self.target/'plans/index.yaml').read_text())['records'][0]
        public_attestation = (self.target/record['path']/'public-plan-attestation.json').read_bytes()
        before = p._tree_fingerprint(self.target)
        # The internal attestation now names another commit; the pinned owner
        # would not verify it for this receiver record, and need not.
        # source_fields reports the resolved canonical locator, as run.py does.
        self.report.update(production_source_commit='c'*40, source_identity=record['source_identity'], plan_revision=1,
                           plan=str(Path(self.report['plan']).resolve()))
        self.next_run('COMMIT')
        def owner_must_not_run(item, internal, child_python=None):
            raise AssertionError('owner verification is not needed for an unchanged record')
        with patch('tools.canonical_plan_projection._owner_bundle', owner_must_not_run):
            result = self.project()
        self.assertEqual('ALREADY_PROJECTED', result['status'])
        self.assertEqual(['P0001'], result['public_ids'])
        self.assertEqual(before, p._tree_fingerprint(self.target))
        self.assertEqual(public_attestation, (self.target/record['path']/'public-plan-attestation.json').read_bytes())
        kept = yaml.safe_load((self.target/'plans/index.yaml').read_text())['records'][0]
        self.assertEqual('a'*40, kept['production_commit'])

    def test_changed_bytes_at_the_same_revision_still_need_a_new_revision(self):
        """Production has no revision bump: changed bytes at revision 1 are a REVISION_CONFLICT."""
        with patch('tools.canonical_plan_projection._owner_bundle', synthetic_owner_boundary):
            self.assertEqual('APPLIED', self.project()['status'])
            record = yaml.safe_load((self.target/'plans/index.yaml').read_text())['records'][0]
            plan = Path(self.report['plan']); plan.write_bytes(plan.read_bytes() + b'\nNew version\n')
            self.report.update(production_plan_sha256=p._sha256_bytes(plan.read_bytes()),
                               source_identity=record['source_identity'], plan_revision=1, plan=str(plan.resolve()))
            self.next_run('BYTES')
            before = p._tree_fingerprint(self.target)
            result = self.project()
        self.assertEqual('BLOCKED_CONFLICT', result['status'])
        self.assertEqual(before, p._tree_fingerprint(self.target))
        evidence = json.loads((self.root/'state'/self.report['run_id']/'public-projection-result.json').read_text())
        self.assertTrue(evidence['findings'][0]['remediation'].endswith('reason: REVISION_CONFLICT'))

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
