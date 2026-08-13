from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from tools.drive_live_bridge import DriveLiveBridge, DriveLiveError, FakeDriveLiveProvider, GoogleDriveProvider
from tools.validate import load_json, load_yaml, validate_drive_live_contract


ROOT = Path(__file__).resolve().parents[1]


def metadata() -> dict:
    return load_json(ROOT / "tests/fixtures/drive/create_metadata.json")


class DriveLiveBridgeTests(unittest.TestCase):
    def test_policy_and_plan_are_create_only_and_metadata_only(self):
        policy = load_yaml(ROOT / "config/drive-live-policy.yaml")
        self.assertEqual([], validate_drive_live_contract(policy, load_json(ROOT / "schemas/drive-live-evidence.schema.json")))
        self.assertNotIn("AGENTIC_ART_GOOGLE_DRIVE_TOKEN", json.dumps(load_json(ROOT / "schemas/drive-live-evidence.schema.json")))
        result = DriveLiveBridge().create(content="synthetic", metadata=metadata(), idempotency_key="interaction:drive-live:plan", mode="plan")
        self.assertEqual("PLANNED", result["status"])
        self.assertEqual("NONE", result["operation"])
        self.assertEqual([], result["remote_operations"])
        self.assertIsNone(result["artifact"])
        self.assertNotIn("synthetic", json.dumps(result))

    def test_live_creates_in_approved_folder_and_verifies_readback(self):
        provider = FakeDriveLiveProvider()
        result = DriveLiveBridge(provider).create(content="synthetic live bytes", metadata=metadata(), idempotency_key="interaction:drive-live:create", mode="live", folder_id="folder-live-sandbox-001", confirm_live=True)
        self.assertEqual("CREATED", result["status"])
        self.assertEqual("CREATE", result["operation"])
        self.assertEqual(1, provider.file_count)
        self.assertEqual(3, len(result["remote_operations"]))
        self.assertNotIn("synthetic live bytes", json.dumps(result))
        self.assertEqual(result["content_hash"], result["artifact"]["content_hash"])

    def test_same_key_replays_without_second_create_and_different_payload_blocks(self):
        provider = FakeDriveLiveProvider()
        bridge = DriveLiveBridge(provider)
        first = bridge.create(content="same", metadata=metadata(), idempotency_key="interaction:drive-live:replay", mode="live", folder_id="folder-live-sandbox-002", confirm_live=True)
        second = bridge.create(content="same", metadata=metadata(), idempotency_key="interaction:drive-live:replay", mode="live", folder_id="folder-live-sandbox-002", confirm_live=True)
        self.assertEqual("REPLAYED", second["status"])
        self.assertEqual("REPLAY", second["operation"])
        self.assertEqual(first["artifact"], second["artifact"])
        self.assertEqual(1, provider.file_count)
        with self.assertRaisesRegex(DriveLiveError, "idempotency key"):
            bridge.create(content="different", metadata=metadata(), idempotency_key="interaction:drive-live:replay", mode="live", folder_id="folder-live-sandbox-002", confirm_live=True)

    def test_process_retry_searches_provider_and_replays_existing_file(self):
        provider = FakeDriveLiveProvider()
        first = DriveLiveBridge(provider).create(content="retry", metadata=metadata(), idempotency_key="interaction:drive-live:process-retry", mode="live", folder_id="folder-live-sandbox-003", confirm_live=True)
        second = DriveLiveBridge(provider).create(content="retry", metadata=metadata(), idempotency_key="interaction:drive-live:process-retry", mode="live", folder_id="folder-live-sandbox-003", confirm_live=True)
        self.assertEqual("REPLAYED", second["status"])
        self.assertEqual(first["artifact"], second["artifact"])
        self.assertEqual(1, provider.file_count)

    def test_invalid_folder_and_provider_failure_are_fail_closed(self):
        with self.assertRaisesRegex(DriveLiveError, "approved folder ID"):
            DriveLiveBridge().create(content="x", metadata=metadata(), idempotency_key="interaction:drive-live:invalid", mode="live", folder_id="root", confirm_live=True)
        with self.assertRaisesRegex(DriveLiveError, "no provider"):
            DriveLiveBridge().create(content="x", metadata=metadata(), idempotency_key="interaction:drive-live:no-provider", mode="live", folder_id="folder-live-sandbox-004", confirm_live=True)

    def test_cli_plan_materialize_and_check(self):
        output = ROOT / "data/drive-live-evidence.json"
        materialize = subprocess.run([sys.executable, str(ROOT / "tools/drive_live_check.py"), "--plan"], capture_output=True, text=True, check=False)
        self.assertEqual(0, materialize.returncode, materialize.stderr)
        checked = subprocess.run([sys.executable, str(ROOT / "tools/drive_live_check.py"), "--plan", "--check"], capture_output=True, text=True, check=False)
        self.assertEqual(0, checked.returncode, checked.stderr)
        self.assertEqual("PLANNED", load_json(output)["status"])

    def test_cli_live_refuses_without_provider(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/drive_live_check.py"), "--live", "--folder-id", "folder-live-sandbox-005"], capture_output=True, text=True, check=False)
        self.assertEqual(2, result.returncode)
        self.assertIn("confirm-live", result.stderr)

    def test_cli_fixture_live_requires_confirmation_and_runs(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/drive_live_check.py"), "--live", "--fixture", "--confirm-live", "--folder-id", "folder-live-sandbox-005"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_google_provider_has_no_mutation_surface(self):
        provider = GoogleDriveProvider("synthetic-token", api_root="https://example.invalid")
        self.assertFalse(hasattr(provider, "update_file"))
        self.assertFalse(hasattr(provider, "delete_file"))
        self.assertFalse(hasattr(provider, "move_file"))


if __name__ == "__main__":
    unittest.main()
