from __future__ import annotations

import importlib.util
import copy
import tempfile
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

    def test_execution_state_rejects_absolute_replay_command_paths(self):
        state = copy.deepcopy(MODULE.load_yaml(ROOT / "execution/state.yaml"))
        state["qualification_v14"]["command"] = (
            ".venv/bin/python tools/release_check.py --workspace-root=/tmp/ephemeral"
        )
        errors = MODULE.validate_execution_state(state, "fixture:execution/state.yaml")
        rendered = "\n".join(errors)
        self.assertIn("qualification_v14.command", rendered)
        self.assertIn("absolute path token", rendered)

    def test_execution_state_accepts_repo_relative_replay_commands(self):
        state = copy.deepcopy(MODULE.load_yaml(ROOT / "execution/state.yaml"))
        self.assertEqual([], MODULE.validate_execution_state(state, "fixture:execution/state.yaml"))

    def test_queue_advances_from_v1_qualification_into_v11(self):
        queue = MODULE.load_yaml(ROOT / "execution/task-queue.yaml")
        by_id = {task["id"]: task for task in queue["tasks"]}
        self.assertEqual("DONE", by_id["RELEASE-001"]["status"])
        self.assertEqual("DONE", by_id["V11-DESIGN-001"]["status"])
        self.assertIn(by_id["ARTIFACT-001"]["status"], {"READY", "IN_PROGRESS", "DONE"})

    def test_issue_ssot_tasks_have_canonical_authority_and_terminal_contract(self):
        queue = MODULE.load_yaml(ROOT / "execution/task-queue.yaml")
        issue_tasks = [task for task in queue["tasks"] if task["id"] in MODULE.ISSUE_SSO_TASK_IDS]
        self.assertEqual(MODULE.ISSUE_SSO_TASK_IDS, {task["id"] for task in issue_tasks})
        errors = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "task-queue.yaml"
            path.write_text(MODULE.yaml.safe_dump(queue, allow_unicode=True, sort_keys=False), encoding="utf-8")
            MODULE.validate_tasks(errors, path)
        self.assertEqual([], errors)

    def test_issue_ssot_task_rejects_incomplete_or_unsafe_metadata(self):
        queue = MODULE.load_yaml(ROOT / "execution/task-queue.yaml")
        task = next(item for item in queue["tasks"] if item["id"] == "GAP-DAG-001")
        task.pop("issue_ssot")
        missing_errors = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing-task-queue.yaml"
            path.write_text(MODULE.yaml.safe_dump(queue, allow_unicode=True, sort_keys=False), encoding="utf-8")
            MODULE.validate_tasks(missing_errors, path)
        self.assertIn("missing issue SSOT field", "\n".join(missing_errors))

        task["issue_ssot"] = "https://example.com/not-an-issue"
        task["target_repositories"] = ["not-in-manifest", "not-in-manifest"]
        task["agent_terminal"] = "MERGE"
        errors = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "task-queue.yaml"
            path.write_text(MODULE.yaml.safe_dump(queue, allow_unicode=True, sort_keys=False), encoding="utf-8")
            MODULE.validate_tasks(errors, path)
        rendered = "\n".join(errors)
        self.assertIn("not a canonical GitHub Issue URL", rendered)
        self.assertIn("target_repositories must be unique", rendered)
        self.assertIn("unknown repository IDs", rendered)
        self.assertIn("agent_terminal is unknown", rendered)

    def test_manifest_preserves_core_roles_and_allows_additions(self):
        manifest = MODULE.load_yaml(ROOT / "config/repositories.yaml")
        roles = [repo["role"] for repo in manifest["repositories"]]
        ids = {repo["id"] for repo in manifest["repositories"]}
        self.assertGreaterEqual(roles.count("input-kb"), 3)
        self.assertGreaterEqual(roles.count("consumer-runtime"), 1)
        self.assertTrue(MODULE.CORE_REPOSITORY_IDS.issubset(ids))
        production = next(repo for repo in manifest["repositories"] if repo["id"] == "agentic-art-production")
        self.assertEqual("control-plane-extension", production["role"])
        self.assertEqual(
            {"imports": ["production-handoff/v1"], "exports": ["production-result/v1"]},
            production["exchange_contracts"],
        )

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

    def test_manifest_instruction_entrypoints_are_authoritative(self):
        manifest = MODULE.load_yaml(ROOT / "config/repositories.yaml")
        repositories = {repository["id"]: repository for repository in manifest["repositories"]}
        expected_ids = {
            "self-model",
            "art-history",
            "marketing-trends",
            "agentic-art-research",
            "agentic-art-production",
            "viewer-response-notes",
        }
        self.assertTrue(expected_ids.issubset(repositories))
        for repository_id in expected_ids:
            with self.subTest(repository_id=repository_id):
                self.assertEqual("AGENTS.md", repositories[repository_id]["instructions"])

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
        self.assertIn("exchange_contracts", repository["properties"])

    def test_public_project_relationship_is_canonical_and_input_isolated(self):
        registry = MODULE.load_yaml(ROOT / "config/repository-relationships.yaml")
        schema = MODULE.load_json(ROOT / "schemas/repository-relationships.schema.json")
        manifest = MODULE.load_yaml(ROOT / "config/repositories.yaml")
        self.assertEqual(
            [],
            MODULE.validate_repository_relationships_contract(
                registry,
                schema,
                manifest,
                "fixture:repository-relationships",
            ),
        )

        relationship = registry["relationships"][0]
        self.assertEqual("masa-san-jp/agentic-art-project", relationship["repository"]["full_name"])
        self.assertEqual("public-output-catalog", relationship["role"])
        self.assertEqual("export-only", relationship["direction"])
        self.assertEqual("public_projection_root", relationship["destination_role"])
        self.assertEqual("private-staging", relationship["lifecycle"]["current"])
        self.assertEqual(["plan"], relationship["projection_policy"]["automatic_records"])
        self.assertEqual("human-gated", relationship["projection_policy"]["git_remote_operations"])
        manifest_ids = {repository["id"] for repository in manifest["repositories"]}
        self.assertNotIn("agentic-art-project", manifest_ids)

    def test_public_project_relationship_rejects_input_or_visibility_expansion(self):
        registry = MODULE.load_yaml(ROOT / "config/repository-relationships.yaml")
        schema = MODULE.load_json(ROOT / "schemas/repository-relationships.schema.json")
        manifest = copy.deepcopy(MODULE.load_yaml(ROOT / "config/repositories.yaml"))

        registry["relationships"][0]["lifecycle"]["current"] = "public-catalog"
        rendered = "\n".join(
            MODULE.validate_repository_relationships_contract(
                registry,
                schema,
                manifest,
                "fixture:visibility-expansion",
            )
        )
        self.assertIn("private-staging", rendered)

        registry = MODULE.load_yaml(ROOT / "config/repository-relationships.yaml")
        added = copy.deepcopy(manifest["repositories"][0])
        added["id"] = "agentic-art-project"
        added["full_name"] = "masa-san-jp/agentic-art-project"
        manifest["repositories"].append(added)
        rendered = "\n".join(
            MODULE.validate_repository_relationships_contract(
                registry,
                schema,
                manifest,
                "fixture:input-expansion",
            )
        )
        self.assertIn("must not be an input manifest repository", rendered)

    def test_production_exchange_contract_is_fail_closed(self):
        manifest = copy.deepcopy(MODULE.load_yaml(ROOT / "config/repositories.yaml"))
        production = next(repo for repo in manifest["repositories"] if repo["id"] == "agentic-art-production")
        production["exchange_contracts"]["exports"] = ["normalized-research-signal/v1"]
        rendered = "\n".join(MODULE.validate_manifest(manifest, "fixture:production-exchange"))
        self.assertIn("exchange_contracts", rendered)
        self.assertIn("production-result/v1", rendered)
        self.assertIn("remediation:", rendered)

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
