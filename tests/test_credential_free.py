from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import credential_free, process_policy


ROOT = Path(__file__).resolve().parents[1]


class CredentialFreeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"

    def invoke(self, command, *, environment=None, cwd=ROOT, timeout=30):
        return subprocess.run(
            [sys.executable, str(ROOT / "tools/credential_free.py"),
             "--state-root", str(self.state), "--", *command],
            cwd=cwd, env=environment, input="annotated answer\n", text=True,
            capture_output=True, timeout=timeout, check=False,
        )

    def test_real_entry_observes_absent_with_hostile_inherited_auth(self):
        repository = self.root / "repository"
        repository.mkdir()
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        for key, value in (
            ("credential.helper", "osxkeychain"),
            ("credential.https://github.com.helper", "!echo test-secret >&2"),
            ("http.https://github.com/.extraheader", "Authorization: test-secret"),
            ("http.https://github.com/masa-san-jp/.extraheader", "Authorization: test-secret"),
        ):
            subprocess.run(["git", "-C", str(repository), "config", key, value], check=True)
        original_config = (repository / ".git/config").read_bytes()
        original_gh = self.root / "original-gh"
        original_gh.mkdir()
        (original_gh / "hosts.yml").write_text("test-secret", encoding="utf-8")
        global_config = self.root / "original-git"
        global_config.write_text("[credential]\nhelper = osxkeychain\n", encoding="utf-8")
        original_home = self.root / "original-home"
        original_home.mkdir()
        (original_home / ".netrc").write_text("machine github.com password test-secret\n", encoding="utf-8")
        environment = dict(os.environ)
        environment.update(
            HOME=str(original_home),
            GH_CONFIG_DIR=str(original_gh), GIT_CONFIG_GLOBAL=str(global_config),
            GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="credential.helper",
            GIT_CONFIG_VALUE_0="!echo test-secret", GIT_CONFIG_PARAMETERS="'credential.helper=secret'",
            SSH_AUTH_SOCK="/test/agent", GIT_SSH_COMMAND="ssh -i /test/key",
            GIT_ASKPASS="/test/askpass", SSH_ASKPASS="/test/askpass",
        )
        for name in process_policy.AUTH_ENV_NAMES:
            environment[name] = "test-secret"
        code = """
import json, os, stat, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tools.process_policy import observe_git_write_credentials, AUTH_ENV_NAMES
gh = Path(os.environ['GH_CONFIG_DIR'])
assert not list(gh.iterdir())
assert stat.S_IMODE(gh.stat().st_mode) == 0o700
assert Path(os.environ['GIT_CONFIG_GLOBAL']).read_bytes() == b''
assert all(name not in os.environ for name in AUTH_ENV_NAMES)
assert 'GIT_CONFIG_PARAMETERS' not in os.environ
assert 'SSH_AUTH_SOCK' not in os.environ
assert os.environ['GIT_TERMINAL_PROMPT'] == '0'
assert os.environ['GIT_CONFIG_NOSYSTEM'] == '1'
assert os.environ['GIT_SSH_COMMAND'].startswith('ssh -F /dev/null ')
assert not list(Path(os.environ['HOME']).iterdir())
header = subprocess.run(['git','config','--get','http.https://github.com/.extraheader'], capture_output=True, text=True)
assert header.stdout == '\\n'
header = subprocess.run(['git','config','--get-urlmatch','http.extraheader','https://github.com/masa-san-jp/self-model-notes'], capture_output=True, text=True)
assert not header.stdout.strip()
fill = subprocess.run(['git','credential','fill'], input='protocol=https\\nhost=github.com\\n\\n', capture_output=True, text=True)
assert fill.returncode != 0
assert 'test-secret' not in fill.stdout + fill.stderr
print(json.dumps({'status': observe_git_write_credentials(), 'stdin': sys.stdin.read()}))
"""
        result = self.invoke([sys.executable, "-c", code, str(ROOT)], environment=environment, cwd=repository)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"status": "absent", "stdin": "annotated answer\n"}, json.loads(result.stdout))
        self.assertNotIn("test-secret", result.stdout + result.stderr)
        self.assertEqual(original_config, (repository / ".git/config").read_bytes())
        self.assertEqual("test-secret", (original_gh / "hosts.yml").read_text())
        self.assertIn("test-secret", (original_home / ".netrc").read_text())
        self.assertEqual([], list(self.state.iterdir()))

    def test_exit_code_stdout_and_stderr_are_forwarded(self):
        result = self.invoke([sys.executable, "-c",
                              "import sys; print('out'); print('err', file=sys.stderr); sys.exit(37)"])
        self.assertEqual(37, result.returncode)
        self.assertEqual("out\n", result.stdout)
        self.assertEqual("err\n", result.stderr)
        self.assertEqual([], list(self.state.iterdir()))

    def test_entry_also_works_outside_a_git_repository(self):
        result = self.invoke([sys.executable, "-c", "print('ok')"], cwd=self.root)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("ok\n", result.stdout)

    def test_relative_state_root_keeps_auth_paths_absolute_after_child_changes_cwd(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/credential_free.py"), "--state-root", "state", "--",
             sys.executable, "-c", "import os; from pathlib import Path; os.chdir('/'); "
             "assert Path(os.environ['GH_CONFIG_DIR']).is_absolute(); "
             "assert Path(os.environ['GH_CONFIG_DIR']).is_dir(); "
             "assert Path(os.environ['GIT_CONFIG_GLOBAL']).is_file()"],
            cwd=self.root, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], list(self.state.iterdir()))

    def test_signal_is_forwarded_after_cleanup(self):
        for signum in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=signum):
                result = self.invoke([sys.executable, "-c", f"import os; os.kill(os.getpid(), {signum})"])
                self.assertEqual(-signum, result.returncode)
                self.assertEqual([], list(self.state.iterdir()))

    def test_missing_command_does_not_print_command_or_secret(self):
        result = self.invoke(["/missing/test-secret"])
        self.assertEqual(127, result.returncode)
        self.assertNotIn("test-secret", result.stdout + result.stderr)
        self.assertEqual([], list(self.state.iterdir()))

    def test_missing_command_argument_is_usage_error(self):
        with patch.object(sys, "stderr"):
            with self.assertRaises(SystemExit) as error:
                credential_free.main(["--state-root", str(self.state), "--"])
        self.assertEqual(2, error.exception.code)
        self.assertFalse(self.state.exists())

    def test_existing_state_is_preserved_and_config_is_fresh_each_time(self):
        self.state.mkdir()
        existing = self.state / "saved-run"
        existing.write_text("existing state", encoding="utf-8")
        first = self.invoke([sys.executable, "-c",
                             "import os; from pathlib import Path; p=Path(os.environ['GH_CONFIG_DIR']); "
                             "print(p); (p/'hosts.yml').write_text('test-secret')"])
        second = self.invoke([sys.executable, "-c",
                              "import os; from pathlib import Path; p=Path(os.environ['GH_CONFIG_DIR']); "
                              "assert not list(p.iterdir()); print(p)"])
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertNotEqual(first.stdout, second.stdout)
        self.assertEqual("existing state", existing.read_text())
        self.assertEqual([existing], list(self.state.iterdir()))

    def test_ssh_has_no_effective_agent_key_or_interactive_auth(self):
        result = self.invoke([sys.executable, "-c", """
import os, shlex, subprocess
result = subprocess.run(shlex.split(os.environ['GIT_SSH_COMMAND']) + ['-G', 'github.com'], capture_output=True, text=True)
assert result.returncode == 0
config = dict(line.split(' ', 1) for line in result.stdout.splitlines())
for key, value in {'identityagent':'none', 'identityfile':'/dev/null', 'identitiesonly':'yes',
                   'batchmode':'yes', 'pubkeyauthentication':'false', 'passwordauthentication':'no',
                   'kbdinteractiveauthentication':'no'}.items():
    assert config[key] == value, (key, config[key])
"""])
        self.assertEqual(0, result.returncode, result.stderr)

    def test_public_repository_can_be_read_without_credentials_when_network_available(self):
        # The one explicitly requested network check is read-only; no gh login
        # or token provisioning is required. Offline CI can skip this probe.
        try:
            result = self.invoke(
                ["git", "ls-remote", "https://github.com/masa-san-jp/self-model-notes"], timeout=20,
            )
        except subprocess.TimeoutExpired:
            self.skipTest("public GitHub read probe timed out")
        if result.returncode != 0:
            unavailable = ("could not resolve", "failed to connect", "network is unreachable",
                           "connection timed out", "couldn't connect", "proxy", "ssl certificate",
                           "connection reset", "operation not permitted")
            if any(message in result.stderr.lower() for message in unavailable):
                self.skipTest("public GitHub read probe unavailable in this network")
        self.assertEqual(0, result.returncode, "public repository read failed")
        self.assertTrue(any(line.endswith("\tHEAD") for line in result.stdout.splitlines()))


class CredentialFreeObservationTests(unittest.TestCase):
    def test_empty_config_does_not_mask_active_helpers_or_git_observation_failure(self):
        with tempfile.TemporaryDirectory() as root:
            for returncode, output in ((0, "osxkeychain\n"), (128, "")):
                with self.subTest(returncode=returncode), \
                        patch.dict(os.environ, {"GH_CONFIG_DIR": root}, clear=True), \
                        patch.object(process_policy.subprocess, "run", return_value=
                                     subprocess.CompletedProcess(["git"], returncode, stdout=output, stderr="")):
                    self.assertEqual("unknown", process_policy.observe_git_write_credentials())

    def test_relative_gh_config_is_resolved_in_observation_cwd(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "gh").mkdir()
            def fake_run(command, **kwargs):
                if command[0] == "gh":
                    raise FileNotFoundError("gh missing")
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
            with patch.dict(os.environ, {"GH_CONFIG_DIR": "gh"}, clear=True), \
                    patch.object(process_policy.subprocess, "run", side_effect=fake_run):
                self.assertEqual("absent", process_policy.observe_git_write_credentials(cwd=Path(root)))

    def test_enterprise_tokens_are_present_and_removed_at_child_boundary(self):
        for name in ("GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
            with self.subTest(name=name), patch.dict(os.environ, {name: "test-secret"}, clear=True):
                self.assertEqual("present", process_policy.observe_git_write_credentials())
                self.assertNotIn(name, process_policy.child_environment())

    def test_empty_config_proves_gh_absence_even_when_gh_is_not_installed(self):
        with tempfile.TemporaryDirectory() as root:
            def fake_run(command, **kwargs):
                if command[0] == "gh":
                    raise FileNotFoundError("gh missing")
                return subprocess.CompletedProcess(command, 0, stdout="osxkeychain\n\n", stderr="")
            with patch.dict(os.environ, {"GH_CONFIG_DIR": root}, clear=True), \
                    patch.object(process_policy.subprocess, "run", side_effect=fake_run):
                self.assertEqual("absent", process_policy.observe_git_write_credentials())

    def test_nonempty_or_symlink_config_does_not_hide_failed_observation(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "gh"
            directory.mkdir()
            (directory / "hosts.yml").write_text("test-secret", encoding="utf-8")
            empty = Path(root) / "empty"
            empty.mkdir()
            link = Path(root) / "link"
            link.symlink_to(empty, target_is_directory=True)
            def fake_run(command, **kwargs):
                if command[0] == "gh":
                    raise FileNotFoundError("gh missing")
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
            for config in (directory, link, Path(root) / "missing"):
                with self.subTest(config=config.name), \
                        patch.dict(os.environ, {"GH_CONFIG_DIR": str(config)}, clear=True), \
                        patch.object(process_policy.subprocess, "run", side_effect=fake_run):
                    self.assertEqual("unknown", process_policy.observe_git_write_credentials())


if __name__ == "__main__":
    unittest.main()
