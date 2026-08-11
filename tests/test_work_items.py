from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "orchestration_validate", ROOT / "tools/validate.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

FIXTURE_DIR = ROOT / "tests/fixtures/work-items"


class WorkItemTests(unittest.TestCase):
    def test_work_item_schema_is_draft_2020_12_and_declares_runtime_fields(self):
        schema = MODULE.load_json(ROOT / "schemas/work-item.schema.json")
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        for field in (
            "owner_repository",
            "allowed_paths",
            "depends_on",
            "checks",
            "risk",
            "attempts",
            "terminal_criteria",
        ):
            self.assertIn(field, schema["required"])

    def test_valid_work_item_passes(self):
        work_item = MODULE.load_yaml(FIXTURE_DIR / "valid.yaml")
        self.assertEqual([], MODULE.validate_work_item(work_item, "fixture:valid"))

    def test_invalid_work_item_matrix_fails_with_remediation(self):
        valid = MODULE.load_yaml(FIXTURE_DIR / "valid.yaml")
        fixtures = MODULE.load_yaml(FIXTURE_DIR / "invalid_cases.yaml")
        for case in fixtures["cases"]:
            with self.subTest(case=case["name"]):
                work_item = copy.deepcopy(valid)
                target = work_item
                for key in case["path"][:-1]:
                    target = target[key]
                target[case["path"][-1]] = case["value"]
                errors = MODULE.validate_work_item(work_item, f"fixture:{case['name']}")
                rendered = "\n".join(errors)
                self.assertTrue(errors, case["name"])
                self.assertIn(case["expected"], rendered)
                self.assertIn("remediation:", rendered)

    def test_done_work_item_requires_observed_commit_and_test_evidence(self):
        work_item = MODULE.load_yaml(FIXTURE_DIR / "valid.yaml")
        work_item["terminal_state"] = "DONE"
        errors = MODULE.validate_work_item(work_item, "fixture:done-without-evidence")
        rendered = "\n".join(errors)
        self.assertIn("commit evidence", rendered)
        self.assertIn("test evidence", rendered)


if __name__ == "__main__":
    unittest.main()
