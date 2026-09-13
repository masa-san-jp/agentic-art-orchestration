from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.autonomous_runner import AutonomousRunnerError, run_autonomous
from tools.delivery_completion import resolve_contract


class AutonomousPlanRecoveryTests(unittest.TestCase):
    def _worker(self, root: Path) -> Path:
        worker = root / "worker.py"
        worker.write_text(
            """#!/usr/bin/env python3
import json
import sys
from pathlib import Path
request = Path(sys.argv[sys.argv.index('--request') + 1])
response = Path(sys.argv[sys.argv.index('--response') + 1])
payload = {
    'contract_version': 'agent-result/v1',
    'run_id': json.loads(request.read_text())['run_id'],
    'stage': 'research',
    'status': 'COMPLETED',
    'checks': [{'id': 'check', 'status': 'PASSED'}],
    'changed_paths': ['project'],
    'commit_sha': 'b' * 40,
    'blocker_category': 'none',
    'requested_operations': [],
}
response.write_text(json.dumps(payload))
""",
            encoding="utf-8",
        )
        worker.chmod(0o755)
        return worker

    def test_resume_rejects_a_changed_delivery_contract(self):
        with tempfile.TemporaryDirectory(prefix="autonomous-plan-recovery-") as temporary:
            root = Path(temporary)
            worker = self._worker(root)
            project = root / "project"
            project.mkdir()
            state = run_autonomous(
                run_id="RECOVERY-001",
                worker_command=str(worker),
                state_root=root / "state",
                source_commit="a" * 40,
                project_path=str(project),
                allowed_paths=("project",),
                once=True,
            )
            state_path = root / "state" / "RECOVERY-001" / "supervisor.json"
            state["delivery_contract"] = {"contract_version": "delivery-contract/v1", "target": "project-local"}
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            with self.assertRaisesRegex(AutonomousRunnerError, "different delivery contract"):
                run_autonomous(
                    run_id="RECOVERY-001",
                    worker_command=str(worker),
                    state_root=root / "state",
                    source_commit="a" * 40,
                    project_path=str(project),
                    allowed_paths=("project",),
                    once=True,
                )

    def test_legacy_cycle_contract_is_preserved_until_explicit_migration(self):
        profile = {"delivery_mode": "public-catalog", "permissions": {"public_projection": True}}
        self.assertEqual(
            {"contract_version": "delivery-contract/v1", "target": "project-committed"},
            resolve_contract(None, profile, legacy_context=True),
        )
        self.assertEqual(
            {"contract_version": "delivery-contract/v1", "target": "project-local"},
            resolve_contract(None, profile),
        )


if __name__ == "__main__":
    unittest.main()
