from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("orchestration_self_hearing", ROOT / "tools/self_hearing.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SelfHearingWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="self-hearing-wrapper-")
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        (self.workspace / "self-model-notes" / "tools").mkdir(parents=True)
        self.profile = self.root / "profile"
        self.profile.mkdir()
        self.state = self.root / "state"
        self.addCleanup(self.temporary.cleanup)

    def _stub(self, body: str) -> None:
        (self.workspace / "self-model-notes" / "tools" / "growth_tasks.py").write_text(body, encoding="utf-8")

    def _main(self, operation: str, *extra: str, stdin: str = "") -> tuple[int, str]:
        output = io.StringIO()
        with patch.object(MODULE, "observe_git_write_credentials", return_value="absent"), \
                patch("sys.stdin", io.StringIO(stdin)), \
                patch("sys.stdout", output):
            code = MODULE.main([
                operation,
                "--run-id", "HEARING-TEST",
                "--state-root", str(self.state),
                "--workspace-root", str(self.workspace),
                "--profile-root", str(self.profile),
                *extra,
            ])
        return code, output.getvalue()

    def _read_outcome(self) -> dict:
        return json.loads((self.state / "HEARING-TEST" / "hearing.json").read_text(encoding="utf-8"))

    def test_open_streams_packet_and_records_only_sanitized_offered_outcome(self):
        self._stub(
            "import json\n"
            "print(json.dumps({'outcome':'offered','reason':None,'question_id':'avoidance',"
            "'intent':['SECRET_INTENT'],'question':'SECRET_QUESTION','anchors':[{'text':'SECRET_ANCHOR'}]}))\n"
        )
        code, stdout = self._main("open", "--purpose", "artistic-research")

        self.assertEqual(0, code)
        self.assertIn("SECRET_QUESTION", stdout)
        self.assertEqual("offered", self._read_outcome()["outcome"])
        self.assertEqual("avoidance", self._read_outcome()["question_id"])
        self.assertEqual({"contract_version", "run_id", "outcome", "reason", "question_id", "ts"}, set(self._read_outcome()))
        state_text = "\n".join(path.read_text(encoding="utf-8") for path in (self.state / "HEARING-TEST").rglob("*" ) if path.is_file())
        self.assertNotIn("SECRET_INTENT", state_text)
        self.assertNotIn("SECRET_QUESTION", state_text)
        self.assertNotIn("SECRET_ANCHOR", state_text)

    def test_open_child_unavailable_is_still_success_and_stdout_is_json(self):
        self._stub("import json\nprint(json.dumps({'outcome':'unavailable','reason':'NO_CONSENTED_SOURCE','question_id':None}))\n")

        code, stdout = self._main("open")

        self.assertEqual(0, code)
        self.assertEqual("unavailable", json.loads(stdout)["outcome"])
        self.assertEqual("NO_CONSENTED_SOURCE", self._read_outcome()["reason"])

    def test_answer_streams_stdin_without_recording_it(self):
        self._stub(
            "import json, sys\n"
            "assert sys.stdin.read() == 'PRIVATE_ANSWER'\n"
            "print(json.dumps({'outcome':'answered','reason':None,'question_id':'avoidance'}))\n"
        )

        def fake_run(command, **kwargs):
            self.assertIs(kwargs["stdin"], sys.stdin)
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"outcome": "answered", "reason": None, "question_id": "avoidance"}), stderr="")

        with patch.object(MODULE.subprocess, "run", side_effect=fake_run):
            code, stdout = self._main("answer", "--task-id", "GT-0001", stdin="PRIVATE_ANSWER")

        self.assertEqual(0, code)
        self.assertEqual("answered", self._read_outcome()["outcome"])
        self.assertNotIn("PRIVATE_ANSWER", stdout)
        self.assertNotIn("PRIVATE_ANSWER", "\n".join(path.read_text(encoding="utf-8") for path in (self.state / "HEARING-TEST").rglob("*") if path.is_file()))

    def test_skip_records_reason_only(self):
        self._stub("import json\nprint(json.dumps({'outcome':'skipped','reason':'no-response','question_id':'avoidance'}))\n")

        code, _ = self._main("skip", "GT-0001", "--reason", "no-response")

        self.assertEqual(0, code)
        self.assertEqual("skipped", self._read_outcome()["outcome"])
        self.assertEqual("no-response", self._read_outcome()["reason"])

    def test_nonzero_timeout_and_old_pin_all_become_unavailable(self):
        self._stub("import sys\nsys.exit(9)\n")
        code, _ = self._main("open")
        self.assertEqual(0, code)
        self.assertEqual({"unavailable", "HEARING_UNAVAILABLE"}, {self._read_outcome()["outcome"], self._read_outcome()["reason"]})

        (self.workspace / "self-model-notes" / "tools" / "growth_tasks.py").unlink()
        code, _ = self._main("open")
        self.assertEqual(0, code)
        self.assertEqual("HEARING_UNAVAILABLE", self._read_outcome()["reason"])

        self._stub("print('never')\n")
        with patch.object(MODULE.subprocess, "run", side_effect=subprocess.TimeoutExpired("child", 30)):
            with patch.object(MODULE, "observe_git_write_credentials", return_value="absent"):
                code, _, _ = MODULE.execute(
                    "open", run_id="TIMEOUT", state_root=self.state, workspace_root=self.workspace,
                    profile_root=self.profile,
                )
        self.assertEqual(0, code)
        timeout_outcome = json.loads((self.state / "TIMEOUT" / "hearing.json").read_text(encoding="utf-8"))
        self.assertEqual("HEARING_UNAVAILABLE", timeout_outcome["reason"])

    def test_child_environment_removes_both_github_tokens_and_helpers(self):
        with patch.dict(os.environ, {"GH_TOKEN": "write-secret", "GITHUB_TOKEN": "another-secret"}, clear=False):
            environment = MODULE.child_environment()

        self.assertNotIn("GH_TOKEN", environment)
        self.assertNotIn("GITHUB_TOKEN", environment)
        self.assertEqual("credential.helper", environment["GIT_CONFIG_KEY_0"])
        self.assertEqual("", environment["GIT_CONFIG_VALUE_0"])


if __name__ == "__main__":
    unittest.main()
