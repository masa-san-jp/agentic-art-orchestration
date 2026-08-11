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


CONFIG = ROOT / "config/transformation-rules.yaml"
FIXTURE_DIR = ROOT / "tests/fixtures/transformation-rules"


class TransformationRuleTests(unittest.TestCase):
    def load_registry(self) -> dict:
        return MODULE.load_yaml(CONFIG)

    def test_rule_schema_is_versioned_and_finite(self):
        schema = MODULE.load_json(ROOT / "schemas/transformation-rule.schema.json")
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertEqual("transformation-rule/v1", schema["properties"]["contract_version"]["const"])
        self.assertIn("composition", schema["$defs"]["rule"]["required"])

    def test_checked_in_registry_passes(self):
        errors = MODULE.validate_transformation_rule_registry(self.load_registry(), "fixture:rules")
        self.assertEqual([], errors)

    def test_invalid_rule_matrix_fails_with_remediation(self):
        valid = self.load_registry()
        for case in MODULE.load_yaml(FIXTURE_DIR / "invalid_cases.yaml")["cases"]:
            with self.subTest(case=case["name"]):
                registry = copy.deepcopy(valid)
                if case.get("mutation") == "duplicate_rule":
                    registry["rules"].append(copy.deepcopy(registry["rules"][0]))
                else:
                    target = registry
                    for key in case["path"][:-1]:
                        target = target[key]
                    target[case["path"][-1]] = case["value"]
                errors = MODULE.validate_transformation_rule_registry(registry, f"fixture:{case['name']}")
                rendered = "\n".join(errors)
                self.assertTrue(errors)
                self.assertIn(case["expected"], rendered)
                self.assertIn("remediation:", rendered)

    def test_rule_slots_must_reference_declared_bindings(self):
        registry = self.load_registry()
        registry["rules"][0]["composition"]["slots"]["personal_tension"]["attribute"] = "seeks"
        errors = MODULE.validate_transformation_rule_registry(registry, "fixture:slot-binding")
        rendered = "\n".join(errors)
        self.assertIn("composition.slots.personal_tension", rendered)
        self.assertIn("remediation:", rendered)

    def test_rule_registry_does_not_authorize_free_form_operations(self):
        registry = self.load_registry()
        registry["rules"][0]["constraints"].append("free_form_ideation")
        errors = MODULE.validate_transformation_rule_registry(registry, "fixture:free-form")
        rendered = "\n".join(errors)
        self.assertIn("constraints", rendered)
        self.assertIn("remediation:", rendered)


if __name__ == "__main__":
    unittest.main()
