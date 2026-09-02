from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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
        self.assertEqual("initial-operations-github-sandbox-v1", self.policy["idempotency_key_prefix"])
        self.assertEqual("fixture-attempt-1", self.policy["fixture_attempt_id"])

    def test_retry_policy_rejects_unbounded_or_non_monotonic_settings(self):
        invalid = dict(self.policy)
        invalid["post_create_search"] = {"max_attempts": 11, "initial_delay_seconds": 9, "backoff_multiplier": 2, "max_delay_seconds": 8}
        errors = validate_github_sandbox_live_contract(invalid, load_json(ROOT / "schemas/github-sandbox-live-evidence.schema.json"), self.manifest)
        self.assertTrue(any("max_attempts" in error for error in errors))
        self.assertTrue(any("initial delay exceeds maximum" in error for error in errors))

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
                run_check(mode="live", confirm_live=True, attempt_id="attempt-a", provider=FixtureProvider(), policy=self.policy, manifest=self.manifest)

    def test_live_attempt_id_is_required_and_invalid_before_provider_read(self):
        class CountingProvider(FixtureProvider):
            def __init__(self):
                super().__init__()
                self.reads = 0

            def get_repository(self, repository: str) -> dict:
                self.reads += 1
                return super().get_repository(repository)

        provider = CountingProvider()
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/dedicated-sandbox"}, clear=False):
            with self.assertRaisesRegex(GithubSandboxLiveError, "attempt ID"):
                run_check(mode="live", confirm_live=True, provider=object(), policy=self.policy, manifest=self.manifest)
            with self.assertRaisesRegex(GithubSandboxLiveError, "attempt ID is invalid"):
                run_check(mode="live", confirm_live=True, attempt_id="Bad-ID", provider=provider, policy=self.policy, manifest=self.manifest)
            with self.assertRaisesRegex(GithubSandboxLiveError, "attempt ID is invalid"):
                run_check(mode="live", confirm_live=True, attempt_id="", provider=provider, policy=self.policy, manifest=self.manifest)
        self.assertEqual(0, provider.reads)

    def test_cli_live_requires_attempt_id_before_token_or_remote_access(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/github_sandbox_live_check.py"), "--live", "--confirm-live"],
            capture_output=True,
            text=True,
            env={"PATH": os.environ.get("PATH", "")},
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("--attempt-id", result.stderr)

    def test_live_rejects_production_repository_before_provider_access(self):
        provider = FixtureProvider()
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/agentic-art-orchestration"}, clear=False):
            with self.assertRaisesRegex(GithubSandboxLiveError, "production repository"):
                run_check(mode="live", confirm_live=True, attempt_id="attempt-a", provider=provider, policy=self.policy, manifest=self.manifest)
        self.assertEqual([], provider.created)

    def test_live_creates_once_then_proves_reuse(self):
        provider = FixtureProvider()
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/dedicated-sandbox"}, clear=False):
            result = run_check(mode="live", confirm_live=True, attempt_id="attempt-a", provider=provider, policy=self.policy, manifest=self.manifest)
        self.assertEqual("CREATED", result["status"])
        self.assertEqual("CREATE", result["operation"])
        self.assertEqual(1, len(provider.created))
        self.assertEqual(["READ", "CREATE", "READ", "REUSE"], [item["operation"] for item in result["remote_operations"]])
        self.assertEqual(hashlib.sha256("initial-operations-github-sandbox-v1:attempt-a".encode()).hexdigest(), result["idempotency_key_hash"])
        self.assertNotIn("dedicated-sandbox", str(result))

    def test_distinct_attempts_create_once_and_same_attempt_reuses(self):
        provider = FixtureProvider()
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/dedicated-sandbox"}, clear=False):
            first = run_check(mode="live", confirm_live=True, attempt_id="attempt-a", provider=provider, policy=self.policy, manifest=self.manifest)
            second = run_check(mode="live", confirm_live=True, attempt_id="attempt-b", provider=provider, policy=self.policy, manifest=self.manifest)
            replay = run_check(mode="live", confirm_live=True, attempt_id="attempt-a", provider=provider, policy=self.policy, manifest=self.manifest)
        self.assertEqual(["CREATED", "CREATED", "REUSED"], [first["status"], second["status"], replay["status"]])
        self.assertEqual(2, len(provider.created))
        self.assertEqual("REUSE", replay["operation"])
        self.assertNotEqual(first["idempotency_key_hash"], second["idempotency_key_hash"])

    def test_live_retries_eventually_consistent_search_without_waiting_in_fixture(self):
        class EventuallyConsistentProvider(FixtureProvider):
            def __init__(self):
                super().__init__()
                self.search_count = 0

            def search(self, repository: str, deduplication_key: str) -> list[dict]:
                self.search_count += 1
                return super().search(repository, deduplication_key) if self.search_count >= 4 else []

        provider = EventuallyConsistentProvider()
        sleeps: list[float] = []
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/dedicated-sandbox"}, clear=False):
            result = run_check(mode="live", confirm_live=True, attempt_id="attempt-a", provider=provider, policy=self.policy, manifest=self.manifest, sleep=sleeps.append)
        self.assertEqual("CREATED", result["status"])
        self.assertEqual(4, provider.search_count)
        self.assertEqual([2.0, 4.0], sleeps)
        self.assertEqual(["READ", "CREATE", "READ", "READ", "READ", "REUSE"], [item["operation"] for item in result["remote_operations"]])
        self.assertEqual([1, 2, 3], [item["attempt"] for item in result["remote_operations"] if item["operation"] == "READ" and "attempt" in item])

    def test_live_blocks_after_finite_post_create_search_attempts(self):
        class NeverIndexedProvider(FixtureProvider):
            def search(self, repository: str, deduplication_key: str) -> list[dict]:
                return []

        policy = dict(self.policy)
        policy["post_create_search"] = {"max_attempts": 3, "initial_delay_seconds": 0, "backoff_multiplier": 2, "max_delay_seconds": 0}
        provider = NeverIndexedProvider()
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/dedicated-sandbox"}, clear=False):
            result = run_check(mode="live", confirm_live=True, attempt_id="attempt-a", provider=provider, policy=policy, manifest=self.manifest, sleep=lambda _: None)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual(1, len(provider.created))
        self.assertEqual(["READ", "CREATE", "READ", "READ", "READ"], [item["operation"] for item in result["remote_operations"]])

    def test_existing_issue_is_reused_without_create(self):
        provider = FixtureProvider([{"number": 9, "url": "https://github.com/masa-san-jp/dedicated-sandbox/issues/9"}])
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/dedicated-sandbox"}, clear=False):
            result = run_check(mode="live", confirm_live=True, attempt_id="attempt-a", provider=provider, policy=self.policy, manifest=self.manifest)
        self.assertEqual("REUSED", result["status"])
        self.assertEqual([], provider.created)
        self.assertEqual(["READ", "REUSE"], [item["operation"] for item in result["remote_operations"]])

    def test_ambiguous_existing_issues_fail_closed_without_create(self):
        provider = FixtureProvider([
            {"number": 9, "url": "https://github.com/masa-san-jp/dedicated-sandbox/issues/9"},
            {"number": 10, "url": "https://github.com/masa-san-jp/dedicated-sandbox/issues/10"},
        ])
        with patch.dict(os.environ, {"AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY": "masa-san-jp/dedicated-sandbox"}, clear=False):
            result = run_check(mode="live", confirm_live=True, attempt_id="attempt-a", provider=provider, policy=self.policy, manifest=self.manifest)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual([], provider.created)


if __name__ == "__main__":
    unittest.main()
