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


BOUNDARY = ROOT / "config/research-execution-boundary.yaml"
FIXTURE_DIR = ROOT / "tests/fixtures/v12-boundary"


class V12BoundaryTests(unittest.TestCase):
    def load_boundary(self) -> dict:
        return MODULE.load_yaml(BOUNDARY)

    def test_boundary_schema_is_versioned_and_metadata_only(self):
        schema = MODULE.load_json(ROOT / "schemas/research-execution-boundary.schema.json")
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertEqual("research-execution-boundary/v1", schema["properties"]["contract_version"]["const"])
        self.assertIn("worker_policy", schema["required"])
        self.assertIn("child_authority", schema["required"])

    def test_checked_in_boundary_passes(self):
        self.assertEqual([], MODULE.validate_research_execution_boundary(self.load_boundary(), "fixture:boundary"))

    def test_invalid_boundary_matrix_fails_with_remediation(self):
        valid = self.load_boundary()
        for case in MODULE.load_yaml(FIXTURE_DIR / "invalid_cases.yaml")["cases"]:
            with self.subTest(case=case["name"]):
                boundary = copy.deepcopy(valid)
                target = boundary
                for key in case["path"][:-1]:
                    target = target[key]
                target[case["path"][-1]] = case["value"]
                errors = MODULE.validate_research_execution_boundary(boundary, f"fixture:{case['name']}")
                rendered = "\n".join(errors)
                self.assertTrue(errors)
                self.assertIn(case["expected"], rendered)
                self.assertIn("remediation:", rendered)

    def test_allowed_and_forbidden_worker_operations_cannot_overlap(self):
        boundary = self.load_boundary()
        boundary["worker_policy"]["forbidden_operations"].append("retrieve")
        errors = MODULE.validate_research_execution_boundary(boundary, "fixture:operation-overlap")
        rendered = "\n".join(errors)
        self.assertIn("overlap", rendered)
        self.assertIn("remediation:", rendered)

    def test_provenance_and_source_requirements_are_complete(self):
        boundary = self.load_boundary()
        boundary["output_policy"]["required_provenance"].remove("source_commit")
        boundary["source_requirements"]["required_fields"].remove("commit")
        errors = MODULE.validate_research_execution_boundary(boundary, "fixture:incomplete-provenance")
        rendered = "\n".join(errors)
        self.assertIn("source_commit", rendered)
        self.assertIn("commit", rendered)


if __name__ == "__main__":
    unittest.main()
