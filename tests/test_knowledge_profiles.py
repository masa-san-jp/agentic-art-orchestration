from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("orchestration_validate", ROOT / "tools/validate.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class KnowledgeProfileTests(unittest.TestCase):
    def test_all_manifest_entries_declare_machine_readable_profiles(self):
        manifest = MODULE.load_yaml(ROOT / "config/repositories.yaml")
        required = {
            "answerable_questions",
            "canonical_entities",
            "retrieval_entry_points",
            "evidence_rules",
            "freshness_rules",
            "feedback_owner",
            "write_scope",
            "forbidden_data",
        }
        for repository in manifest["repositories"]:
            with self.subTest(repository=repository["id"]):
                profile = repository["knowledge_profile"]
                self.assertTrue(required.issubset(profile))
                self.assertTrue(profile["evidence_rules"]["requires_locator"])
                self.assertTrue(
                    MODULE.REQUIRED_PROFILE_FORBIDDEN_DATA.issubset(
                        set(profile["forbidden_data"])
                    )
                )
        self.assertEqual([], MODULE.validate_manifest(manifest))

    def test_missing_profile_field_is_rejected_with_remediation(self):
        manifest = copy.deepcopy(MODULE.load_yaml(ROOT / "config/repositories.yaml"))
        del manifest["repositories"][0]["knowledge_profile"]["write_scope"]
        rendered = "\n".join(MODULE.validate_manifest(manifest, "fixture:missing-profile"))
        self.assertIn("knowledge_profile.write_scope", rendered)
        self.assertIn("remediation:", rendered)

    def test_profile_owner_evidence_and_write_boundaries_are_rejected(self):
        manifest = copy.deepcopy(MODULE.load_yaml(ROOT / "config/repositories.yaml"))
        profile = manifest["repositories"][0]["knowledge_profile"]
        profile["feedback_owner"] = "unknown-repository"
        profile["evidence_rules"]["requires_locator"] = False
        profile["write_scope"]["allowed_paths"] = ["../outside"]
        profile["forbidden_data"] = ["PRIVATE_RAW"]
        rendered = "\n".join(MODULE.validate_manifest(manifest, "fixture:profile-boundary"))
        self.assertIn("feedback_owner", rendered)
        self.assertIn("requires_locator", rendered)
        self.assertIn("allowed_paths", rendered)
        self.assertIn("baseline classes", rendered)
        self.assertIn("remediation:", rendered)

    def test_schema_exposes_profile_contract(self):
        schema = MODULE.load_json(ROOT / "schemas/repository-manifest.schema.json")
        profile = schema["$defs"]["knowledge_profile"]
        self.assertIn("knowledge_profile", schema["$defs"])
        self.assertIn("answerable_questions", profile["required"])
        self.assertIn("retrieval_entry_points", profile["required"])
        self.assertIn("write_scope", profile["required"])


if __name__ == "__main__":
    unittest.main()
