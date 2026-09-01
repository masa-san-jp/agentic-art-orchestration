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
                "masa-san-jp/viewer-response-notes",
            },
            checkout_repositories,
        )
        credential_index = next(
            index
            for index, step in enumerate(real_chain["steps"])
            if step.get("name") == "Verify read-only private child repository credential"
        )
        first_checkout_index = next(
            index for index, step in enumerate(real_chain["steps"]) if step.get("uses") == "actions/checkout@v4"
        )
        self.assertLess(credential_index, first_checkout_index)
        expected_refs = {
            "masa-san-jp/self-model-notes": "main",
            "masa-san-jp/art-history-notes": "main",
            "masa-san-jp/marketing-trends-notes": "main",
            "masa-san-jp/agentic-art-research": "main",
            "masa-san-jp/agentic-art-production": "main",
            "masa-san-jp/viewer-response-notes": "feat/viewer-response-contracts",
        }
        for step in real_chain["steps"]:
            if step.get("uses") == "actions/checkout@v4" and "repository" in step.get("with", {}):
                self.assertEqual(expected_refs[step["with"]["repository"]], step["with"]["ref"])
                self.assertEqual(0, step["with"]["fetch-depth"])
                self.assertFalse(step["with"]["persist-credentials"])
        qualification = next(step for step in real_chain["steps"] if step.get("name") == "Qualify the real immutable exchange chain")
        command = qualification["run"]
        self.assertIn("tools/qualify_pin_update.py", command)
        self.assertIn("--workspace-root repos", command)
        self.assertIn("--run-id ci-real-chain", command)
        self.assertNotIn("--apply", command)

    def test_private_child_access_requires_an_external_actions_secret(self):
        workflow = self.workflow()
        real_chain = workflow["jobs"]["real-chain"]
        credential_step = next(step for step in real_chain["steps"] if step.get("name") == "Verify read-only private child repository credential")
        self.assertIn("AAP_CHILD_REPOS_TOKEN", credential_step["env"]["AAP_CHILD_REPOS_TOKEN"])
        self.assertIn("MISSING_EXTERNAL_SECRET", credential_step["run"])
        self.assertIn("AAP_CHILD_REPOS_TOKEN", credential_step["run"])
        for step in real_chain["steps"]:
            if step.get("uses") == "actions/checkout@v4" and "repository" in step.get("with", {}):
                self.assertIn("AAP_CHILD_REPOS_TOKEN", step["with"]["token"])
                self.assertFalse(step["with"]["persist-credentials"])

    def test_real_chain_does_not_log_secret_or_apply_pin_changes(self):
        workflow = self.workflow()
        real_chain = workflow["jobs"]["real-chain"]
        serialized = str(real_chain)
        self.assertNotIn("echo $AAP_CHILD_REPOS_TOKEN", serialized)
        qualification = next(step for step in real_chain["steps"] if step.get("name") == "Qualify the real immutable exchange chain")
        self.assertNotIn("--apply", qualification["run"])


if __name__ == "__main__":
    unittest.main()
