from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "orchestration_validate", ROOT / "tools/validate.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def valid_artifact() -> dict:
    with (ROOT / "tests/fixtures/artifacts/valid.json").open(encoding="utf-8") as handle:
        return json.load(handle)


class ExternalArtifactContractTests(unittest.TestCase):
    def test_schema_declares_create_only_google_drive_envelope(self):
        schema = MODULE.load_json(ROOT / "schemas/external-artifact.schema.json")
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertEqual("external-artifact/v1", schema["properties"]["contract_version"]["const"])
        self.assertEqual("CREATE", schema["properties"]["operation"]["const"])
        self.assertEqual("google-drive", schema["properties"]["provider"]["const"])
        self.assertFalse(schema["additionalProperties"])

    def test_valid_artifact_preserves_opaque_reference_hash_and_provenance(self):
        artifact = valid_artifact()
        original = copy.deepcopy(artifact)
        self.assertEqual([], MODULE.validate_external_artifact(artifact, "fixture:valid"))
        self.assertEqual(original, artifact)
        self.assertEqual(64, len(artifact["content_hash"]))
        self.assertEqual(2, len(artifact["source_snapshots"]))

    def test_update_delete_and_content_fields_are_rejected(self):
        for operation in ("UPDATE", "DELETE"):
            with self.subTest(operation=operation):
                artifact = valid_artifact()
                artifact["operation"] = operation
                errors = MODULE.validate_external_artifact(artifact, f"fixture:{operation}")
                rendered = "\n".join(errors)
                self.assertIn("operation", rendered)
                self.assertIn("CREATE", rendered)
                self.assertIn("remediation:", rendered)

        artifact = valid_artifact()
        artifact["content"] = "synthetic content must remain outside Git"
        rendered = "\n".join(MODULE.validate_external_artifact(artifact, "fixture:content"))
        self.assertIn("unknown field", rendered)

    def test_provider_hash_access_and_source_snapshot_are_strict(self):
        mutations = (
            ("provider", lambda item: item.__setitem__("provider", "local-filesystem"), "provider"),
            ("file_url", lambda item: item.__setitem__("provider_file_id", "https://drive.google.com/file/1"), "provider_file_id"),
            ("hash", lambda item: item.__setitem__("content_hash", "not-a-hash"), "content_hash"),
            ("consent", lambda item: item["access"].__setitem__("consent_scope", ""), "consent_scope"),
            ("repository", lambda item: item["source_snapshots"][0].__setitem__("repository", "unknown-repo"), "source_snapshots[0].repository"),
        )
        for name, mutate, expected in mutations:
            with self.subTest(case=name):
                artifact = valid_artifact()
                mutate(artifact)
                rendered = "\n".join(
                    MODULE.validate_external_artifact(artifact, f"fixture:{name}")
                )
                self.assertIn(expected, rendered)
                self.assertIn("remediation:", rendered)

    def test_duplicate_source_and_self_lineage_are_rejected(self):
        artifact = valid_artifact()
        artifact["source_snapshots"].append(copy.deepcopy(artifact["source_snapshots"][0]))
        artifact["lineage"]["derived_from"] = [artifact["artifact_id"]]
        rendered = "\n".join(
            MODULE.validate_external_artifact(artifact, "fixture:lineage")
        )
        self.assertIn("source_snapshots repositories must be unique", rendered)
        self.assertIn("must not reference itself", rendered)
        self.assertIn("remediation:", rendered)


if __name__ == "__main__":
    unittest.main()
