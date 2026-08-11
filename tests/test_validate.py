from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "orchestration_validate", ROOT / "tools/validate.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class BootstrapValidationTests(unittest.TestCase):
    def test_bootstrap_is_valid(self):
        self.assertEqual([], MODULE.validate())

    def test_queue_has_single_initial_ready_task(self):
        queue = MODULE.load_yaml(ROOT / "execution/task-queue.yaml")
        ready = [task["id"] for task in queue["tasks"] if task["status"] == "READY"]
        self.assertEqual(["MANIFEST-001"], ready)

    def test_manifest_declares_three_inputs_and_one_consumer(self):
        manifest = MODULE.load_yaml(ROOT / "config/repositories.yaml")
        roles = [repo["role"] for repo in manifest["repositories"]]
        self.assertEqual(3, roles.count("input-kb"))
        self.assertEqual(1, roles.count("consumer-runtime"))


if __name__ == "__main__":
    unittest.main()
