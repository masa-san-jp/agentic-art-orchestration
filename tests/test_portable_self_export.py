from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tools import ingest_signals, run, security, self_export
from tools.signal_fixtures import synthetic_self_export

ROOT = Path(__file__).resolve().parents[1]


def portable(*, empty=False):
    source = synthetic_self_export()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    source["generated_at"] = now.isoformat()
    if empty:
        source["signals"] = []
        source["signal_count"] = 0
    return {"contract_version": self_export.CONTRACT, "export_id": "synthetic-export-273",
            "generated_at": source["generated_at"], "expires_at": (now + timedelta(hours=1)).isoformat(),
            "source_commit": source["source_commit"], "content_sha256": self_export.content_hash(source), "payload": source}


class PortableSelfExportTests(unittest.TestCase):
    def test_valid_envelope_retains_original_id_hash_and_commit_without_payload_in_receipt(self):
        value = portable()
        payload, receipt = self_export.validate_portable(value, "artistic-research")
        self.assertEqual(value["payload"], payload)
        for field in ("export_id", "content_sha256", "source_commit", "generated_at", "expires_at"):
            self.assertEqual(value[field], receipt[field])
        self.assertEqual("portable-self-export-receipt/v1", receipt["contract_version"])
        self.assertNotIn("payload", receipt)
        self.assertNotIn("signals", receipt)

    def test_invalid_expiry_hash_source_scope_and_consent_are_rejected(self):
        def rehash(value):
            value["content_sha256"] = self_export.content_hash(value["payload"])
        mutations = [
            (lambda v: v.update(expires_at="2000-01-01T00:00:00Z"), "SELF_EXPORT_INVALID"),
            (lambda v: v.update(expires_at="invalid"), "SELF_EXPORT_INVALID"),
            (lambda v: v.update(generated_at="2026-10-04"), "SELF_EXPORT_INVALID"),
            (lambda v: v.update(content_sha256="sha256:" + "0" * 64), "SELF_EXPORT_HASH_MISMATCH"),
            (lambda v: v.update(source_commit="123"), "SELF_EXPORT_INVALID"),
            (lambda v: v["payload"].update(source_repository="art-history"), "SELF_EXPORT_SCOPE_MISMATCH"),
            (lambda v: v["payload"].update(purpose="other-purpose"), "SELF_EXPORT_SCOPE_MISMATCH"),
            (lambda v: v["payload"].update(source_commit="bad"), "SELF_EXPORT_INVALID"),
            (lambda v: v["payload"]["signals"][0].update(commit="a" * 40), "SELF_EXPORT_INVALID"),
            (lambda v: v["payload"]["signals"][0].update(export_permitted=False), "SELF_EXPORT_INVALID"),
            (lambda v: v["payload"]["signals"][0].update(consent_scope="denied"), "SELF_EXPORT_INVALID"),
        ]
        for mutate, code in mutations:
            with self.subTest(code=code):
                value = portable()
                mutate(value)
                if code != "SELF_EXPORT_HASH_MISMATCH":
                    rehash(value)
                with self.assertRaisesRegex(self_export.SelfExportError, code):
                    self_export.validate_portable(value, "artistic-research")
        value = portable()
        with self.assertRaisesRegex(self_export.SelfExportError, "SELF_EXPORT_EXPIRED"):
            self_export.validate_portable(value, "artistic-research", now=datetime.now(timezone.utc) + timedelta(hours=2))

    def test_expired_input_is_rejected_before_workspace_and_child_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            value = portable()
            value["generated_at"] = value["payload"]["generated_at"] = "2000-01-01T00:00:00Z"
            value["expires_at"] = "2000-01-02T00:00:00Z"
            value["content_sha256"] = self_export.content_hash(value["payload"])
            path = Path(directory) / "export.json"
            path.write_text(json.dumps(value))
            with patch.object(run, "_prepare_runtime_workspace") as workspace, patch.object(run, "_run_tool") as tool:
                with self.assertRaisesRegex(run.BlockedPrecondition, "SELF_EXPORT_EXPIRED"):
                    run._run_orchestration(None, Path(directory), Path(directory) / "state", "expired", "artistic-research", None, None, "now", sys.executable, self_export=path)
            workspace.assert_not_called()
            tool.assert_not_called()
            self.assertFalse((Path(directory) / "state").exists())

    def test_invalid_input_preserves_ingest_output_before_running_other_exporters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "bad.json"
            path.write_text("{}")
            output = root / "signals"
            output.mkdir()
            old = output / "portfolio.json"
            old.write_text("preserve")
            with patch.object(ingest_signals, "_export") as exporter:
                with self.assertRaisesRegex(ingest_signals.IngestBlocked, "SELF_EXPORT_INVALID"):
                    ingest_signals.ingest(root, output, "artistic-research", sys.executable, self_export=path)
            exporter.assert_not_called()
            self.assertEqual("preserve", old.read_text())
            for content in ('{"payload":NaN}', '{"payload":{},"payload":{}}', 'not json'):
                path.write_text(content)
                with self.assertRaisesRegex(self_export.SelfExportError, "SELF_EXPORT_INVALID"):
                    self_export.read_export(path, "artistic-research")
            with self.assertRaisesRegex(self_export.SelfExportError, "SELF_EXPORT_INVALID"):
                self_export.content_hash({"unexpected": float("nan")})

    def test_empty_owner_export_blocks_before_candidate_generation_and_records_remediation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = ingest_signals.IngestBlocked("SELF_MODEL_EMPTY: no exportable self signal", self_export.EMPTY_REMEDIATION)
            failure = run.BlockedPrecondition(str(blocked))
            failure.report = blocked.report()
            with patch.object(run, "_prepare_runtime_workspace", return_value=({"status": "PASSED"}, root)), \
                    patch.object(run, "_run_tool", side_effect=failure) as tool, \
                    patch.object(run, "_manifest_runtime_roots", return_value=(root / "research", root / "production")):
                with self.assertRaisesRegex(run.BlockedPrecondition, "SELF_MODEL_EMPTY"):
                    run._run_orchestration(None, root, root / "state", "empty", "artistic-research", None, None, "now", sys.executable, profile_root=root / "profile")
            self.assertEqual(1, tool.call_count)
            report = json.loads((root / "state/empty/run.json").read_text())
            self.assertEqual("SELF_MODEL_EMPTY", report["stop_reason"])
            self.assertEqual("BLOCKED", report["status"])
            self.assertIn("init", report["remediation"])
            self.assertTrue(report["next_action"]["resume_command"])
            self.assertEqual("INCOMPLETE", report["delivery_completion"]["status"])

    def test_ingest_uses_portable_payload_without_invoking_self_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "export.json"
            path.write_text(json.dumps(portable()))
            manifest = {"repositories": [{"id": "self-model", "path": "absent", "role": "input-kb"}]}
            with patch.object(ingest_signals, "load_yaml", return_value=manifest), \
                    patch.object(ingest_signals, "_export") as exporter, \
                    patch.object(ingest_signals, "_observed_head", return_value=None):
                report = ingest_signals.ingest(root, root / "signals", "artistic-research", sys.executable, self_export=path)
            exporter.assert_not_called()
            self.assertEqual(3, report["by_kind"]["self"])
            self.assertEqual("synthetic-export-273", report["self_export"]["export_id"])

    def test_empty_profile_or_portable_export_produces_same_blocked_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = portable(empty=True)
            manifest = {"repositories": [{"id": "self-model", "path": "absent", "role": "input-kb"}]}
            path = root / "export.json"
            path.write_text(json.dumps(value))
            for options in ({"profile_root": root / "profile"}, {"self_export": path}):
                with patch.object(ingest_signals, "load_yaml", return_value=manifest), \
                        patch.object(ingest_signals, "_export", return_value=value["payload"]):
                    with self.assertRaisesRegex(ingest_signals.IngestBlocked, "SELF_MODEL_EMPTY") as blocked:
                        ingest_signals.ingest(root, root / "signals", "artistic-research", sys.executable, **options)
                remediation = blocked.exception.remediation
                self.assertIn("Event", remediation)
                self.assertIn("Claim", remediation)
                self.assertIn("育成 session", remediation)
                self.assertIn("確認して", remediation)
                self.assertIn(self_export.GROWTH_GUIDE, remediation)
                if "self_export" in options:
                    self.assertNotIn("ヒアリング", remediation)
                    self.assertIn("再書き出し", remediation)
                    self.assertIn("本人記録のある機械", remediation)
                else:
                    self.assertIn("ヒアリング", remediation)
                self.assertFalse((root / "signals").exists())
            checkout = root / "self-model/tools"
            checkout.mkdir(parents=True)
            (checkout / "export_signals.py").write_text("# synthetic exporter")
            denied = subprocess.CompletedProcess([], 1, stdout="", stderr='Export denied\n{"private":"must-not-be-copied"}')
            with patch.object(ingest_signals.subprocess, "run", return_value=denied):
                with self.assertRaisesRegex(ingest_signals.IngestBlocked, "SELF_MODEL_EXPORT_BLOCKED") as error:
                    ingest_signals._export({"id": "self-model", "path": "self-model"}, root, "artistic-research", sys.executable, root / "profile")
            self.assertNotIn("must-not-be-copied", str(error.exception))

    def test_receiver_hearing_is_unavailable_and_resume_preserves_export_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "export.json"
            path.write_text(json.dumps(portable()))
            (root / "state/receiver").mkdir(parents=True)
            (root / "state/receiver/hearing.json").write_text('{"outcome":"answered"}')
            stop = run.StepFailure("candidate probe")
            with patch.object(run, "_prepare_runtime_workspace", return_value=({"status": "PASSED"}, root)), \
                    patch.object(run, "_manifest_runtime_roots", return_value=(root / "research", root / "production")), \
                    patch.object(run, "_run_tool", side_effect=[{"status": "PASSED", "self_export": {"export_id": "probe"}}, stop]) as tool:
                with self.assertRaisesRegex(run.StepFailure, "candidate probe"):
                    run._run_orchestration(None, root, root / "state", "receiver", "artistic-research", None, None, "now", sys.executable, self_export=path)
            receipt = json.loads((root / "state/receiver/self-export-receipt.json").read_text())
            self.assertEqual("probe", receipt["self_export"]["export_id"])
            self.assertEqual({"status": "unavailable", "reason": "PROFILE_ROOT_UNAVAILABLE"}, receipt["self_hearing"])
            self.assertNotIn("payload", receipt["self_export"])
            args = tool.call_args_list[0].args[0]
            self.assertIn("--self-export", args)
            self.assertNotIn("--profile-root", args)
            command = run._resume_command(python=sys.executable, run_id="receiver", workspace_root=root, state_root=root, research_root=None, production_root=None, research_work_root=None, profile_root=None, self_export=path, purpose="artistic-research", intent=None, slug=None, title=None, offline_fixture=False)
            self.assertEqual(str(path), command[command.index("--self-export") + 1])

    def test_repository_paths_are_rejected_even_when_ignored_or_symlinked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root / "git")], check=True)
            for path in (ROOT / "data/ignored-export.json", root / "git/export.json"):
                with self.assertRaisesRegex(self_export.SelfExportError, "REPOSITORY_OVERLAP"):
                    self_export.external_path(path)
            (root / "alias").symlink_to(root / "git", target_is_directory=True)
            with self.assertRaisesRegex(self_export.SelfExportError, "REPOSITORY_OVERLAP"):
                self_export.external_path(root / "alias/export.json")

    def test_export_writer_is_create_only_and_owner_access_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = portable()
            with patch.object(run, "_guard_pinned_workspace"), patch.object(ingest_signals, "_export", return_value=value["payload"]):
                report = self_export.create_export(root, root / "profile", root / "new.json", "artistic-research", value["expires_at"], sys.executable)
                self.assertEqual("PASSED", report["status"])
                self.assertEqual(0o600, (root / "new.json").stat().st_mode & 0o777)
                before = (root / "new.json").read_bytes()
                with self.assertRaisesRegex(self_export.SelfExportError, "SELF_EXPORT_EXISTS"):
                    self_export.create_export(root, root / "profile", root / "new.json", "artistic-research", value["expires_at"], sys.executable)
                self.assertEqual(before, (root / "new.json").read_bytes())

    def test_tracked_exports_block_privacy_and_validator_even_with_renamed_files(self):
        from tools import validate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            value = portable()
            path = root / "notes.txt"
            path.write_text(json.dumps(value))
            subprocess.run(["git", "-C", str(root), "add", "notes.txt"], check=True)
            # Index content alone is sufficient, even if the working file is cleared.
            path.write_text("{}")
            findings = security.tracked_self_exports(root)
            self.assertEqual(["TRACKED_SELF_EXPORT"], [f["code"] for f in findings])
            self.assertNotIn("synthetic-export-273", json.dumps(findings))
            with patch.object(validate, "ROOT", root), patch.object(validate, "REQUIRED_FILES", []):
                errors = validate.validate()
            self.assertTrue(any("TRACKED_SELF_EXPORT" in error for error in errors))
            path.write_text(json.dumps({"nested": value["payload"]}))
            self.assertEqual("TRACKED_SELF_EXPORT", security.tracked_self_exports(root)[0]["code"])

    def test_existing_contract_fixture_has_no_blanket_fixture_exemption(self):
        self.assertEqual([], security.tracked_self_exports(ROOT))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            target = root / "tests/fixtures/signal/self_export_bundle.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(portable()["payload"]))
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            self.assertEqual("TRACKED_SELF_EXPORT", security.tracked_self_exports(root)[0]["code"])

    def test_self_ingest_requires_explicit_git_external_output_before_exporters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export = root / "export.json"
            export.write_text(json.dumps(portable()))
            foreign = root / "foreign"
            subprocess.run(["git", "init", "-q", str(foreign)], check=True)
            alias = root / "alias"
            alias.symlink_to(foreign, target_is_directory=True)
            for options in ({"profile_root": root / "profile"}, {"self_export": export}):
                for output in (None, ROOT / "data/signals", foreign, alias / "signals"):
                    with self.subTest(options=list(options), output=output), \
                            patch.object(ingest_signals, "_export") as exporter:
                        code = "SELF_SIGNAL_OUTPUT_REQUIRED" if output is None else "SELF_SIGNAL_OUTPUT_REPOSITORY_OVERLAP"
                        with self.assertRaisesRegex(ingest_signals.IngestBlocked, code):
                            ingest_signals.ingest(root, output, "artistic-research", sys.executable, **options)
                        exporter.assert_not_called()
            self.assertFalse((foreign / "signals").exists())
            ignored = subprocess.run(["git", "check-ignore", "data/signals/self-model/generated.json"], cwd=ROOT, capture_output=True)
            self.assertEqual(0, ignored.returncode)

    def test_self_ingest_cli_without_output_blocks_and_does_not_write_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export = root / "export.json"
            export.write_text(json.dumps(portable()))
            stderr = io.StringIO()
            with patch.object(ingest_signals, "_export") as exporter, redirect_stderr(stderr):
                code = ingest_signals.main(["--purpose", "artistic-research", "--self-export", str(export)])
            self.assertEqual(2, code)
            self.assertEqual("SELF_SIGNAL_OUTPUT_REQUIRED", json.loads(stderr.getvalue())["stop_reason"])
            exporter.assert_not_called()

    def test_tracked_template_is_fictional_and_contract_is_instantiated_in_memory(self):
        template = json.loads((ROOT / "tests/fixtures/signal/self_export_bundle.json").read_text())
        self.assertEqual("subject/fixture", template["subject"])
        self.assertEqual("synthetic-self-signal-template/v1", template["fixture_version"])
        self.assertNotIn("contract_version", template)
        bundle = synthetic_self_export()
        self_export.validate_payload(bundle, "artistic-research")
        self.assertEqual("0" * 40, bundle["source_commit"])
        self.assertEqual(3, bundle["signal_count"])
        for record in bundle["signals"]:
            self.assertIn("架空の subject/fixture", record["statement"])
            self.assertTrue(record["entity_id"].startswith("claim/fixture-fiction-"))


if __name__ == "__main__":
    unittest.main()
