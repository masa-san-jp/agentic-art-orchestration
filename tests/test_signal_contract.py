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

FIXTURE_DIR = ROOT / "tests/fixtures/signal"


def load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class SignalContractTests(unittest.TestCase):
    def test_signal_schema_is_draft_2020_12_and_declares_v1_envelope(self):
        schema = MODULE.load_json(ROOT / "schemas/normalized-research-signal.schema.json")
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertEqual("normalized-research-signal/v1", schema["properties"]["contract_version"]["const"])
        for field in (
            "source",
            "evidence_refs",
            "certainty",
            "unknowns",
            "freshness",
            "adapter",
        ):
            self.assertIn(field, schema["required"])

    def test_all_domain_fixtures_are_valid(self):
        for name in ("valid_self.json", "valid_art_history.json", "valid_marketing.json"):
            with self.subTest(fixture=name):
                signal = load_fixture(name)
                self.assertEqual([], MODULE.validate_signal(signal, f"fixture:{name}"))

    def test_invalid_signal_matrix_fails_with_remediation(self):
        valid = load_fixture("valid_self.json")
        fixtures = MODULE.load_yaml(FIXTURE_DIR / "invalid_cases.yaml")
        for case in fixtures["cases"]:
            with self.subTest(case=case["name"]):
                signal = copy.deepcopy(valid)
                target = signal
                for key in case["path"][:-1]:
                    target = target[key]
                leaf = case["path"][-1]
                if case.get("remove"):
                    del target[leaf]
                else:
                    target[leaf] = case["value"]
                errors = MODULE.validate_signal(signal, f"fixture:{case['name']}")
                rendered = "\n".join(errors)
                self.assertTrue(errors, case["name"])
                self.assertIn(case["expected"], rendered)
                self.assertIn("remediation:", rendered)

    def test_signal_preserves_source_commit_and_evidence_entity(self):
        signal = load_fixture("valid_self.json")
        signal["source"]["commit"] = "0" * 40
        signal["evidence_refs"][0]["entity_id"] = "not-declared"
        errors = MODULE.validate_signal(signal, "fixture:provenance")
        rendered = "\n".join(errors)
        self.assertIn("evidence_refs[0].entity_id", rendered)
        self.assertEqual("0" * 40, signal["source"]["commit"])

    def test_stale_signal_requires_explicit_constraint_and_non_valid_status(self):
        signal = load_fixture("valid_marketing.json")
        signal["freshness"]["status"] = "stale"
        signal["validity"]["status"] = "stale"
        signal["domain"]["marketing"]["freshness"] = "stale"
        signal["constraints"] = ["This signal is stale and must be revalidated."]
        signal["domain"]["marketing"]["prediction_status"] = "pending"
        self.assertEqual([], MODULE.validate_signal(signal, "fixture:stale-valid"))


if __name__ == "__main__":
    unittest.main()
