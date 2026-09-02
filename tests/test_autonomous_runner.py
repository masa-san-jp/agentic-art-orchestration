from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from tools.autonomous_runner import (
    HUMAN_OPERATIONS,
    run_autonomous,
    validate_agent_action,
    validate_agent_result,
    validate_autonomous_state,
)
from tools.run import run
from tools.signal_bundle import build_signal_bundle


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40
WORKER_COMMIT = "b" * 40


def _signals() -> list[dict]:
    return [
        json.loads((ROOT / "tests/fixtures/signal" / name).read_text(encoding="utf-8"))
        for name in ("valid_self.json", "valid_art_history.json", "valid_marketing.json")
    ]


class AutonomousRunnerTests(unittest.TestCase):
    def worker(self, directory: Path, mode: str, sleep: float = 0) -> tuple[Path, Path]:
        count = directory / "worker-count"
        script = directory / f"worker-{mode}.py"
        script.write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env python3
                import json
                import time
                from pathlib import Path
                request = Path(__import__('sys').argv[__import__('sys').argv.index('--request') + 1])
                response = Path(__import__('sys').argv[__import__('sys').argv.index('--response') + 1])
                count = Path({str(count)!r})
                current = int(count.read_text()) if count.exists() else 0
                count.write_text(str(current + 1))
                time.sleep({sleep!r})
                payload = {{
                    'contract_version': 'agent-result/v1',
                    'run_id': json.loads(request.read_text())['run_id'],
                    'stage': 'research',
                    'status': 'COMPLETED',
                    'checks': [{{'id': 'research-check', 'status': 'PASSED'}}],
                    'changed_paths': ['project'],
                    'commit_sha': {WORKER_COMMIT!r},
                    'blocker_category': 'none',
                    'requested_operations': [],
                }}
                if {mode!r} == 'fail':
                    payload.update({{'status': 'FAILED', 'commit_sha': None, 'blocker_category': 'retryable'}})
                elif {mode!r} == 'human':
                    payload.update({{'status': 'BLOCKED', 'commit_sha': None, 'blocker_category': 'human', 'requested_operations': ['release']}})
                elif {mode!r} == 'privacy':
                    payload['raw_conversation'] = 'must never be persisted'
                response.write_text(json.dumps(payload))
                """
            ).lstrip(),
            encoding="utf-8",
        )
        script.chmod(0o755)
        return script, count

    def call(self, temporary: Path, worker: Path, *, once: bool = False, run_id: str = "runner-test") -> dict:
        project = temporary / "project"
        project.mkdir(exist_ok=True)
        return run_autonomous(
            run_id=run_id,
            worker_command=str(worker),
            state_root=temporary / "state",
            source_commit=COMMIT,
            project_path=str(project),
            allowed_paths=("project",),
            once=once,
        )

    def test_networkless_worker_reaches_plan_ready_and_resume_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="autonomous-runner-") as directory:
            temporary = Path(directory)
            worker, count = self.worker(temporary, "complete")
            first = self.call(temporary, worker, once=True)
            second = self.call(temporary, worker, once=True)
            self.assertEqual("PLAN_READY", first["status"])
            self.assertEqual(first, second)
            self.assertEqual("1", count.read_text())
            self.assertEqual([], validate_autonomous_state(second))
            self.assertEqual(1, len(second["history"]))

    def test_failed_worker_retries_three_times_then_exhausts_on_fourth_failure(self):
        with tempfile.TemporaryDirectory(prefix="autonomous-runner-") as directory:
            temporary = Path(directory)
            worker, count = self.worker(temporary, "fail")
            state = self.call(temporary, worker)
            self.assertEqual("FAILED_RETRY_EXHAUSTED", state["status"])
            self.assertEqual("4", count.read_text())
            self.assertEqual(4, state["attempts"])
            self.assertEqual("FAILED", state["history"][-1]["outcome"])

    def test_human_gate_is_blocked_and_worker_operation_is_not_executed(self):
        with tempfile.TemporaryDirectory(prefix="autonomous-runner-") as directory:
            temporary = Path(directory)
            worker, count = self.worker(temporary, "human")
            state = self.call(temporary, worker)
            self.assertEqual("BLOCKED_HUMAN", state["status"])
            self.assertEqual("1", count.read_text())
            self.assertTrue(set(HUMAN_OPERATIONS).issuperset({"release"}))

    def test_invalid_worker_response_is_rejected_without_raw_value_in_supervisor_state(self):
        with tempfile.TemporaryDirectory(prefix="autonomous-runner-") as directory:
            temporary = Path(directory)
            worker, count = self.worker(temporary, "privacy")
            state = self.call(temporary, worker)
            self.assertEqual("FAILED_RETRY_EXHAUSTED", state["status"])
            serialized = (temporary / "state" / "runner-test" / "supervisor.json").read_text()
            self.assertNotIn("must never be persisted", serialized)
            self.assertEqual("4", count.read_text())

    def test_same_run_lease_rejects_concurrent_process(self):
        with tempfile.TemporaryDirectory(prefix="autonomous-runner-") as directory:
            temporary = Path(directory)
            worker, _count = self.worker(temporary, "complete", sleep=1.0)
            project = temporary / "project"
            project.mkdir()
            state_root = temporary / "state"
            command = [
                sys.executable,
                str(ROOT / "tools/autonomous_runner.py"),
                "--run-id", "concurrent-test",
                "--state-root", str(state_root),
                "--worker-command", str(worker),
                "--source-commit", COMMIT,
                "--project-path", str(project),
                "--allowed-path", "project",
                "--once",
            ]
            first = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            state_path = state_root / "concurrent-test" / "supervisor.json"
            for _ in range(50):
                if state_path.exists() and "RESEARCH_WORKER_RUNNING" in state_path.read_text():
                    break
                time.sleep(0.02)
            second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            first_output = first.communicate(timeout=5)
            self.assertEqual(2, second.returncode)
            self.assertIn("active lease", second.stderr)
            self.assertEqual(0, first.returncode, first_output[1])

    def test_action_result_contracts_are_closed_and_run_emits_structured_pending_action(self):
        bundle = build_signal_bundle(_signals(), "2026-08-27T00:00:00+09:00")
        result = run(bundle, project_id="runner-test", seed_input="seed")
        action = result["next_action"]
        self.assertEqual("RESEARCH_PENDING", result["execution_status"])
        self.assertEqual([], validate_agent_action(action))
        invalid = dict(action)
        invalid["raw_conversation"] = "hidden"
        self.assertTrue(validate_agent_action(invalid))
        self.assertTrue(validate_agent_result({"contract_version": "agent-result/v1"}))


if __name__ == "__main__":
    unittest.main()
