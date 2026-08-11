from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from tools.drive_adapter import DriveArtifactAdapter, DriveArtifactError, FakeDrive
from tools.validate import validate_external_artifact


ROOT = Path(__file__).resolve().parents[1]


def metadata() -> dict:
    with (ROOT / "tests/fixtures/drive/create_metadata.json").open(encoding="utf-8") as handle:
        return json.load(handle)


class DriveAdapterTests(unittest.TestCase):
    def test_create_returns_opaque_reference_hash_and_keeps_content_external(self):
        drive = FakeDrive()
        adapter = DriveArtifactAdapter(drive)
        payload = "synthetic output stays in the external fake"
        original_metadata = metadata()

        result = adapter.create_artifact(
            content=payload,
            metadata=original_metadata,
            idempotency_key="interaction:drive-test:001",
        )
        artifact = result["artifact"]

        self.assertTrue(result["created"])
        self.assertEqual("CREATE", result["operation"])
        self.assertEqual([], validate_external_artifact(artifact, "fixture:drive-output"))
        self.assertRegex(artifact["provider_file_id"], r"^[A-Za-z0-9_-]+$")
        self.assertEqual(64, len(artifact["content_hash"]))
        self.assertEqual(payload.encode("utf-8"), drive.read_content(artifact["provider_file_id"]))
        self.assertEqual([{"operation": "CREATE", "provider_file_id": artifact["provider_file_id"]}], drive.operations)
        self.assertEqual(original_metadata, metadata())
        self.assertNotIn(payload, json.dumps(artifact))
        self.assertEqual([], validate_external_artifact(adapter.registry_snapshot()[0], "fixture:registry"))

    def test_same_idempotency_key_replays_without_duplicate_create(self):
        drive = FakeDrive()
        adapter = DriveArtifactAdapter(drive)
        first = adapter.create_artifact(
            content=b"same bytes",
            metadata=metadata(),
            idempotency_key="interaction:drive-test:replay",
        )
        second = adapter.create_artifact(
            content=b"same bytes",
            metadata=metadata(),
            idempotency_key="interaction:drive-test:replay",
        )

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual("REPLAY", second["operation"])
        self.assertEqual(first["artifact"], second["artifact"])
        self.assertEqual(1, drive.file_count())
        self.assertEqual(1, len(adapter.registry_snapshot()))

    def test_idempotency_conflict_and_duplicate_artifact_id_do_not_create(self):
        drive = FakeDrive()
        adapter = DriveArtifactAdapter(drive)
        adapter.create_artifact(
            content="first",
            metadata=metadata(),
            idempotency_key="interaction:drive-test:conflict",
        )
        with self.assertRaisesRegex(DriveArtifactError, "idempotency key"):
            adapter.create_artifact(
                content="second",
                metadata=metadata(),
                idempotency_key="interaction:drive-test:conflict",
            )
        with self.assertRaisesRegex(DriveArtifactError, "artifact_id"):
            adapter.create_artifact(
                content="third",
                metadata=metadata(),
                idempotency_key="interaction:drive-test:other",
            )
        self.assertEqual(1, drive.file_count())
        self.assertEqual(1, len(drive.operations))

    def test_update_and_delete_are_rejected_without_drive_mutation(self):
        drive = FakeDrive()
        adapter = DriveArtifactAdapter(drive)
        with self.assertRaisesRegex(DriveArtifactError, "UPDATE"):
            adapter.update_artifact("drive-file-001", "replacement")
        with self.assertRaisesRegex(DriveArtifactError, "DELETE"):
            adapter.delete_artifact("drive-file-001")
        with self.assertRaisesRegex(DriveArtifactError, "UPDATE"):
            drive.update_file("drive-file-001", b"replacement")
        with self.assertRaisesRegex(DriveArtifactError, "DELETE"):
            drive.delete_file("drive-file-001")
        self.assertEqual([], drive.operations)
        self.assertEqual(0, drive.file_count())

    def test_invalid_metadata_fails_before_external_create(self):
        mutations = (
            ("operation", {"operation": "UPDATE"}, "UPDATE"),
            ("provider", {"provider": "local-filesystem"}, "provider"),
            ("content", {"content": "must not enter metadata"}, "unknown field"),
            ("file_id", {"provider_file_id": "existing-file"}, "provider_file_id"),
        )
        for name, mutation, expected in mutations:
            with self.subTest(case=name):
                drive = FakeDrive()
                adapter = DriveArtifactAdapter(drive)
                invalid = metadata()
                invalid.update(mutation)
                with self.assertRaisesRegex(DriveArtifactError, expected):
                    adapter.create_artifact(
                        content="payload",
                        metadata=invalid,
                        idempotency_key=f"interaction:drive-test:{name}",
                    )
                self.assertEqual(0, drive.file_count())
                self.assertEqual([], drive.operations)

    def test_different_keys_append_new_immutable_artifacts(self):
        drive = FakeDrive()
        adapter = DriveArtifactAdapter(drive)
        first_metadata = metadata()
        second_metadata = metadata()
        second_metadata["artifact_id"] = "artifact:drive-test:002"
        second_metadata["interaction_id"] = "interaction:drive-test:002"
        first = adapter.create_artifact(
            content="first output",
            metadata=first_metadata,
            idempotency_key="interaction:drive-test:append-1",
        )
        second = adapter.create_artifact(
            content="second output",
            metadata=second_metadata,
            idempotency_key="interaction:drive-test:append-2",
        )

        self.assertNotEqual(first["artifact"]["provider_file_id"], second["artifact"]["provider_file_id"])
        self.assertNotEqual(first["artifact"]["content_hash"], second["artifact"]["content_hash"])
        self.assertEqual(2, drive.file_count())
        self.assertEqual(2, len(adapter.registry_snapshot()))

    def test_output_and_inputs_are_not_mutated(self):
        drive = FakeDrive()
        adapter = DriveArtifactAdapter(drive)
        source = metadata()
        before = copy.deepcopy(source)
        result = adapter.create_artifact(
            content="immutable test",
            metadata=source,
            idempotency_key="interaction:drive-test:immutable",
        )

        self.assertEqual(before, source)
        result["artifact"]["provider_file_id"] = "tampered"
        self.assertNotEqual("tampered", adapter.registry_snapshot()[0]["provider_file_id"])


if __name__ == "__main__":
    unittest.main()
