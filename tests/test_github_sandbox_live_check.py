from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.github_sandbox_live_check import FixtureProvider, GithubSandboxLiveError, run_check
from tools.validate import load_json, load_yaml, validate_github_sandbox_live_contract


ROOT = Path(__file__).resolve().parents[1]


class GithubSandboxLiveCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_yaml(ROOT / "config/github-sandbox-live-policy.yaml")
        self.manifest = load_yaml(ROOT / "config/repositories.yaml")

    def test_policy_and_schema_are_closed_and_separate(self):
        self.assertEqual([], validate_github_sandbox_live_contract(self.policy, load_json(ROOT / "schemas/github-sandbox-live-evidence.schema.json"), self.manifest))

    def test_plan_has_no_remote_operations_and_is_deterministic(self):
        first = run_check(policy=self.policy, manifest=self.manifest)
        second = run_check(policy=self.policy, manifest=self.manifest)
        self.assertEqual(first, second)
        self.assertEqual("PLANNED", first["status"])
        self.assertEqual([], first["remote_operations"])
        self.assertEqual("PLAN", first["mode"])

    def test_live_requires_confirmation_and_explicit_repository(self):
        with self.assertRaisesRegex(GithubSandboxLiveError, "confirm-live"):
            run_check(mode="live", provider=FixtureProvider(), policy=self.policy, manifest=self.manifest)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(GithubSandboxLiveError, "AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY"):
                run_check(mode="live", confirm_live=True, provider=FixtureProvider(), policy=self.policy, manifest=self.manifest)

    def test_live_rejects_production_repository_before_provider_access(self):
        provider = FixtureProvider()
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/agentic-art-orchestration"}, clear=False):
            with self.assertRaisesRegex(GithubSandboxLiveError, "production repository"):
                run_check(mode="live", confirm_live=True, provider=provider, policy=self.policy, manifest=self.manifest)
        self.assertEqual([], provider.created)

    def test_live_creates_once_then_proves_reuse(self):
        provider = FixtureProvider()
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/dedicated-sandbox"}, clear=False):
            result = run_check(mode="live", confirm_live=True, provider=provider, policy=self.policy, manifest=self.manifest)
        self.assertEqual("CREATED", result["status"])
        self.assertEqual("CREATE", result["operation"])
        self.assertEqual(1, len(provider.created))
        self.assertEqual(["READ", "CREATE", "READ", "REUSE"], [item["operation"] for item in result["remote_operations"]])
        self.assertNotIn("dedicated-sandbox", str(result))

    def test_existing_issue_is_reused_without_create(self):
        provider = FixtureProvider([{"number": 9, "url": "https://github.com/masa-san-jp/dedicated-sandbox/issues/9"}])
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/dedicated-sandbox"}, clear=False):
            result = run_check(mode="live", confirm_live=True, provider=provider, policy=self.policy, manifest=self.manifest)
        self.assertEqual("REUSED", result["status"])
        self.assertEqual([], provider.created)
        self.assertEqual(["READ", "REUSE"], [item["operation"] for item in result["remote_operations"]])

    def test_ambiguous_existing_issues_fail_closed_without_create(self):
        provider = FixtureProvider([
            {"number": 9, "url": "https://github.com/masa-san-jp/dedicated-sandbox/issues/9"},
            {"number": 10, "url": "https://github.com/masa-san-jp/dedicated-sandbox/issues/10"},
        ])
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/dedicated-sandbox"}, clear=False):
            result = run_check(mode="live", confirm_live=True, provider=provider, policy=self.policy, manifest=self.manifest)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual([], provider.created)


if __name__ == "__main__":
    unittest.main()
