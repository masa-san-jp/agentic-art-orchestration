from __future__ import annotations

import importlib.util
import copy
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

    def test_queue_advances_from_v1_qualification_into_v11(self):
        queue = MODULE.load_yaml(ROOT / "execution/task-queue.yaml")
        by_id = {task["id"]: task for task in queue["tasks"]}
        self.assertEqual("DONE", by_id["RELEASE-001"]["status"])
        self.assertEqual("DONE", by_id["V11-DESIGN-001"]["status"])
        self.assertIn(by_id["ARTIFACT-001"]["status"], {"READY", "IN_PROGRESS", "DONE"})

    def test_manifest_preserves_core_roles_and_allows_additions(self):
        manifest = MODULE.load_yaml(ROOT / "config/repositories.yaml")
        roles = [repo["role"] for repo in manifest["repositories"]]
        ids = {repo["id"] for repo in manifest["repositories"]}
        self.assertGreaterEqual(roles.count("input-kb"), 3)
        self.assertGreaterEqual(roles.count("consumer-runtime"), 1)
        self.assertTrue(MODULE.CORE_REPOSITORY_IDS.issubset(ids))

        added = copy.deepcopy(manifest["repositories"][0])
        added.update(
            {
                "id": "additional-knowledge",
                "full_name": "masa-san-jp/additional-knowledge-notes",
                "url": "https://github.com/masa-san-jp/additional-knowledge-notes.git",
                "path": "additional-knowledge-notes",
                "authority": "additional synthetic knowledge and evidence",
                "observed_commit": "a" * 40,
                "requirement_ssot": "https://github.com/masa-san-jp/additional-knowledge-notes/issues/1",
            }
        )
        manifest["repositories"].append(added)
        self.assertEqual([], MODULE.validate_manifest(manifest, "fixture:additional"))

    def test_manifest_rejects_replacing_core_repo_and_ambiguous_ownership(self):
        manifest = copy.deepcopy(MODULE.load_yaml(ROOT / "config/repositories.yaml"))
        manifest["repositories"][0]["id"] = "replacement-model"
        rendered = "\n".join(MODULE.validate_manifest(manifest, "fixture:replacement"))
        self.assertIn("missing core repository IDs", rendered)

        manifest = copy.deepcopy(MODULE.load_yaml(ROOT / "config/repositories.yaml"))
        manifest["repositories"][1]["authority"] = manifest["repositories"][0]["authority"]
        rendered = "\n".join(MODULE.validate_manifest(manifest, "fixture:authority"))
        self.assertIn("duplicate authority", rendered)

    def test_requirement_ssot_must_belong_to_declared_repository(self):
        manifest = copy.deepcopy(MODULE.load_yaml(ROOT / "config/repositories.yaml"))
        manifest["repositories"][0]["requirement_ssot"] = (
            "https://github.com/masa-san-jp/another-repository/issues/1"
        )
        rendered = "\n".join(MODULE.validate_manifest(manifest, "fixture:ssot"))
        self.assertIn("requirement_ssot", rendered)
        self.assertIn("same repository", rendered)

    def test_manifest_schema_is_draft_2020_12_and_declares_contract_boundary(self):
        schema = MODULE.load_json(ROOT / "schemas/repository-manifest.schema.json")
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertEqual(4, schema["properties"]["repositories"]["minItems"])
        self.assertNotIn("maxItems", schema["properties"]["repositories"])
        repository = schema["$defs"]["repository"]
        self.assertIn("export_contract", repository["properties"])
        self.assertIn("import_contract", repository["properties"])

    def test_invalid_manifest_fixtures_fail_with_remediation(self):
        valid = MODULE.load_yaml(ROOT / "config/repositories.yaml")
        fixtures = MODULE.load_yaml(ROOT / "tests/fixtures/manifest/invalid_cases.yaml")
        for case in fixtures["cases"]:
            with self.subTest(case=case["name"]):
                manifest = copy.deepcopy(valid)
                target = manifest
                for key in case["path"][:-1]:
                    target = target[key]
                target[case["path"][-1]] = case["value"]
                errors = MODULE.validate_manifest(manifest, f"fixture:{case['name']}")
                rendered = "\n".join(errors)
                self.assertTrue(errors, case["name"])
                self.assertIn(case["expected"], rendered)
                self.assertIn("remediation:", rendered)

    def test_manifest_schema_rejects_missing_required_field(self):
        manifest = MODULE.load_yaml(ROOT / "config/repositories.yaml")
        del manifest["repositories"][0]["quality_gates"]
        errors = MODULE.validate_manifest(manifest)
        self.assertTrue(any("quality_gates" in error and "required" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
