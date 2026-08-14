from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class RealChainCITests(unittest.TestCase):
    def workflow(self) -> dict:
        return yaml.safe_load((ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8"))

    def test_real_chain_checks_all_registered_children_without_pin_or_child_mutation(self):
        workflow = self.workflow()
        real_chain = workflow["jobs"]["real-chain"]
        self.assertEqual("read", real_chain["permissions"]["contents"])
        checkout_repositories = {
            step["with"]["repository"]
            for step in real_chain["steps"]
            if step.get("uses") == "actions/checkout@v4" and "repository" in step.get("with", {})
        }
        self.assertEqual(
            {
                "masa-san-jp/self-model-notes",
                "masa-san-jp/art-history-notes",
                "masa-san-jp/marketing-trends-notes",
                "masa-san-jp/agentic-art-research",
                "masa-san-jp/agentic-art-production",
            },
            checkout_repositories,
        )
        for step in real_chain["steps"]:
            if step.get("uses") == "actions/checkout@v4" and "repository" in step.get("with", {}):
                self.assertEqual("main", step["with"]["ref"])
                self.assertEqual(0, step["with"]["fetch-depth"])
        qualification = next(step for step in real_chain["steps"] if step.get("name") == "Qualify the real immutable exchange chain")
        command = qualification["run"]
        self.assertIn("tools/qualify_pin_update.py", command)
        self.assertIn("--workspace-root repos", command)
        self.assertIn("--run-id ci-real-chain", command)
        self.assertNotIn("--apply", command)


if __name__ == "__main__":
    unittest.main()
