from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import credential_free, profile_root_config as config, run, self_hearing

ROOT = Path(__file__).resolve().parents[1]


class ProfileRootConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.profile = self.root / "private profile 雪"
        self.profile.mkdir()
        self.workspace = self.root / "workspace"
        owner = self.workspace / "self-model-notes" / "tools"
        owner.mkdir(parents=True)
        # This double tests the subprocess boundary; native owner validation is
        # additionally exercised in the separately recorded synthetic probe.
        (owner / "profile_root.py").write_text(
            "import json,sys\nfrom pathlib import Path\n"
            "p=Path(sys.argv[sys.argv.index('--profile-root')+1])\n"
            "print(json.dumps({'status':'PASS' if (p/'valid').exists() else 'BLOCKED'}))\n"
            "sys.exit(0 if (p/'valid').exists() else 2)\n")
        (self.profile / "valid").touch()
        self.environment = {"HOME": str(self.home), "PATH": os.environ['PATH']}
        self.env_patch = patch.dict(os.environ, self.environment, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = config.main(list(args))
        self.assertNotIn(str(self.profile), out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def save(self):
        self.assertEqual(0, self.invoke("set", str(self.profile), "--workspace-root", str(self.workspace))[0])

    def test_precedence_and_sources(self):
        self.assertEqual((None, "none"), config.discover())
        self.save()
        self.assertEqual((self.profile, "user-config"), config.discover())
        alternate = self.root / "alternate"
        with patch.dict(os.environ, {config.ENV: str(alternate)}):
            self.assertEqual((alternate, "env"), config.discover())
            self.assertEqual((self.profile, "argument"), config.discover(self.profile))
        self.assertEqual((self.profile, "argument"), config.discover(self.profile))

    def test_set_show_clear_and_private_mode(self):
        self.save()
        path = config.config_path()
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        self.assertEqual(str(self.profile) + "\n", path.read_text())
        self.assertEqual("user-config", json.loads(self.invoke("show", "--redacted")[1])["profile_root_source"])
        self.assertEqual("user-config", json.loads(self.invoke("show")[1])["profile_root_source"])
        self.assertEqual(0, self.invoke("clear")[0])
        self.assertEqual(0, self.invoke("clear")[0])
        self.assertEqual((None, "none"), config.discover())

    def test_xdg_precedes_home(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "settings")}):
            self.save()
            self.assertTrue((self.root / "settings/agentic-art/profile-root").is_file())
            self.assertEqual((self.profile, "user-config"), config.discover())
        self.assertEqual((None, "none"), config.discover())

    def test_invalid_profile_cannot_replace_valid_setting(self):
        self.save()
        previous = config.config_path().read_bytes()
        (self.profile / "valid").unlink()
        self.assertEqual(2, self.invoke("set", str(self.profile), "--workspace-root", str(self.workspace))[0])
        self.assertEqual(previous, config.config_path().read_bytes())

    def test_native_resolver_failure_output_is_not_echoed(self):
        owner = self.workspace / "self-model-notes/tools/profile_root.py"
        owner.write_text("import sys\nprint(sys.argv, file=sys.stderr)\nsys.exit(2)\n")
        self.assertEqual(2, self.invoke("set", str(self.profile), "--workspace-root", str(self.workspace))[0])
        self.assertFalse(config.config_path().exists())

    def test_relative_repository_and_symlink_roots_reject(self):
        alias = self.root / "alias"
        alias.symlink_to(self.profile, target_is_directory=True)
        repository = self.root / "repository"
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        inside = repository / "ignored-profile"
        inside.mkdir()
        (repository / ".gitignore").write_text("ignored-profile/\n")
        for root in (Path("relative"), inside, alias, alias / "nested", ROOT / "ignored-profile"):
            with self.subTest(kind=root.name):
                self.assertEqual(2, self.invoke("set", str(root), "--workspace-root", str(self.workspace))[0])
        self.assertFalse(config.config_path().exists())

    def test_config_rejects_bad_permissions_multiline_relative_and_special_file(self):
        self.save()
        path = config.config_path()
        path.chmod(0o644)
        with self.assertRaises(config.ProfileConfigError):
            config.discover()
        self.assertEqual(2, self.invoke("show", "--redacted")[0])
        path.chmod(0o600)
        for body in ("", "relative\n", str(self.profile) + "\nextra\n"):
            path.write_text(body)
            with self.assertRaises(config.ProfileConfigError):
                config.discover()
        path.unlink()
        os.mkfifo(path, 0o600)
        with self.assertRaises(config.ProfileConfigError):
            config.discover()

    def test_config_symlink_and_git_location_reject_without_modification(self):
        self.save()
        path = config.config_path()
        original = path.read_bytes()
        target = self.root / "target"
        target.write_bytes(original)
        path.unlink()
        path.symlink_to(target)
        for operation in ("show", "clear"):
            self.assertEqual(2, self.invoke(operation)[0])
        self.assertEqual(original, target.read_bytes())
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(ROOT)}):
            with self.assertRaises(config.ProfileConfigError):
                config.discover()

    def test_explicit_argument_and_env_do_not_read_bad_user_config(self):
        self.save()
        config.config_path().chmod(0o644)
        self.assertEqual((self.profile, "argument"), config.discover(self.profile))
        with patch.dict(os.environ, {config.ENV: str(self.profile)}):
            self.assertEqual((self.profile, "env"), config.discover())

    def test_credential_entry_preserves_user_config_before_home_isolation(self):
        self.save()
        probe = self.root / "probe.py"
        probe.write_text("import os,sys\nsys.path.insert(0,sys.argv[1])\n"
                         "from tools.profile_root_config import discover\n"
                         "root,source=discover()\n"
                         "assert str(root)==sys.argv[2]\n"
                         "assert os.environ['HOME']!=sys.argv[3]\n"
                         "print(source)\n")
        result = subprocess.run([sys.executable, str(ROOT / "tools/credential_free.py"),
                                 "--state-root", str(self.root / "state"), "--", sys.executable,
                                 str(probe), str(ROOT), str(self.profile), str(self.home)],
                                env=dict(os.environ), capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("user-config", result.stdout.strip())
        self.assertNotIn(str(self.profile), result.stdout + result.stderr)

    def test_portable_offline_and_explicit_credential_commands_bypass_config(self):
        self.save()
        config.config_path().chmod(0o644)
        for option in ("--self-export", "--self-export=input", "--profile-root", "--offline-fixture"):
            with patch.object(credential_free, "discover", side_effect=AssertionError("must not resolve")), \
                    patch.object(credential_free.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")):
                self.assertEqual(0, credential_free.launch([sys.executable, "-c", "pass", option], state_root=self.root / "state"))

    def test_run_records_source_and_redacts_child_output_and_resume(self):
        self.save()
        def tool(args, python):
            if args[0] == "tools/ingest_signals.py":
                self.assertEqual(str(self.profile), args[args.index("--profile-root") + 1])
                failure = run.BlockedPrecondition("SELF_MODEL_EMPTY: " + str(self.profile))
                failure.report = {"status": "BLOCKED", "detail": str(self.profile), "nested": {"private": str(self.profile)}}
                raise failure
        state = self.root / "state"
        with patch.object(run, "_guard_pinned_workspace", return_value={"status": "PASSED"}), \
                patch.object(run, "_manifest_runtime_roots", return_value=(None, None)), \
                patch.object(run, "_run_tool", side_effect=tool), \
                redirect_stderr(io.StringIO()) as stderr:
            code = run.main(["--workspace-root", str(self.workspace), "--state-root", str(state), "--run-id", "CONFIG"])
        self.assertEqual(2, code)
        report_text = (state / "CONFIG/run.json").read_text()
        report = json.loads(report_text)
        self.assertEqual("user-config", report["profile_root_source"])
        self.assertNotIn(str(self.profile), report_text + stderr.getvalue())
        self.assertNotIn("--profile-root", report["next_action"]["resume_command"])

    def test_run_missing_configuration_has_owner_setup_remediation(self):
        with patch.object(run, "_guard_pinned_workspace", return_value={"status": "PASSED"}), \
                patch.object(run, "_manifest_runtime_roots", return_value=(None, None)), \
                redirect_stderr(io.StringIO()) as stderr:
            code = run.main(["--workspace-root", str(self.workspace), "--state-root", str(self.root / "state")])
        self.assertEqual(2, code)
        report = json.loads(stderr.getvalue())
        self.assertEqual("PROFILE_ROOT_REQUIRED", report["stop_reason"])
        self.assertEqual("none", report["profile_root_source"])
        self.assertIn("tools/profile_root_config.py set", report["remediation"])
        self.assertIn("パスを人に聞かず", report["remediation"])

    def test_portable_and_offline_run_do_not_discover_profile(self):
        with patch.object(run, "discover", side_effect=AssertionError("must not discover")), \
                patch.object(run, "_run_orchestration_impl", return_value={}) as impl:
            run._run_orchestration(None, self.workspace, self.root / "state", "TEST", "artistic-research", None, None,
                                   "now", sys.executable, None, None, 1, True)
            self.assertEqual("none", impl.call_args.kwargs["profile_root_source"])
            run._run_orchestration(None, self.workspace, self.root / "state", "TEST", "artistic-research", None, None,
                                   "now", sys.executable, self_export=self.root / "export")
            self.assertEqual("none", impl.call_args.kwargs["profile_root_source"])

    def test_hearing_discovery_redaction_and_missing_best_effort_contract(self):
        self.save()
        growth = self.workspace / "self-model-notes/tools/growth_tasks.py"
        growth.write_text("import json,sys\nprint(json.dumps({'outcome':'offered','reason':None,'question_id':'question',"
                          "'packet':sys.argv[sys.argv.index('--profile-root')+1]}))\n")
        args = ["open", "--run-id", "HEARING", "--state-root", str(self.root / "state"),
                "--workspace-root", str(self.workspace)]
        with patch.object(self_hearing, "observe_git_write_credentials", return_value="absent"), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(0, self_hearing.main(args))
        self.assertNotIn(str(self.profile), out.getvalue())
        report = json.loads((self.root / "state/HEARING/run.json").read_text())
        self.assertEqual("user-config", report["profile_root_source"])
        config.config_path().unlink()
        with patch.object(self_hearing, "observe_git_write_credentials", return_value="absent"), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(0, self_hearing.main(args))
        self.assertEqual("PROFILE_ROOT_REQUIRED", json.loads(out.getvalue())["reason"])

    def test_run_errors_redact_oserror_filename_and_report_source(self):
        for source in ("argument", "env"):
            with self.subTest(source=source):
                environment = {config.ENV: str(self.profile)} if source == "env" else {}
                args = ["--workspace-root", str(self.workspace), "--state-root", str(self.root / "state")]
                if source == "argument":
                    args += ["--profile-root", str(self.profile)]
                with patch.dict(os.environ, environment), \
                        patch.object(run, "_run_orchestration_impl", side_effect=OSError(13, "denied", str(self.profile))), \
                        redirect_stderr(io.StringIO()) as stderr:
                    self.assertEqual(1, run.main(args))
                self.assertNotIn(str(self.profile), stderr.getvalue())

    def test_resume_command_never_stores_explicit_profile_path(self):
        command = run._resume_command(python=sys.executable, run_id="TEST", workspace_root=self.workspace,
                                      state_root=self.root / "state", research_root=None, production_root=None,
                                      research_work_root=None, profile_root=self.profile, purpose="artistic-research",
                                      intent=None, slug=None, title=None, offline_fixture=False)
        self.assertNotIn(str(self.profile), command)
        self.assertNotIn("--profile-root", command)


if __name__ == "__main__":
    unittest.main()
