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


def valid_event() -> dict:
    with (ROOT / "tests/fixtures/interactions/valid.json").open(encoding="utf-8") as handle:
        return json.load(handle)


class InteractionContractTests(unittest.TestCase):
    def test_schema_declares_privacy_minimal_experience_outcome(self):
        schema = MODULE.load_json(ROOT / "schemas/interaction-event.schema.json")
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertEqual("interaction-event/v1", schema["properties"]["contract_version"]["const"])
        privacy = schema["$defs"]["privacy"]["properties"]
        self.assertFalse(privacy["raw_conversation_stored"]["const"])
        self.assertFalse(privacy["direct_identifiers_stored"]["const"])

    def test_valid_event_preserves_intent_sources_outcome_and_artifact_reference(self):
        event = valid_event()
        original = copy.deepcopy(event)
        self.assertEqual([], MODULE.validate_interaction_event(event, "fixture:valid"))
        self.assertEqual(original, event)
        self.assertEqual("create", event["intent"]["category"])
        self.assertEqual(2, len(event["source_snapshots"]))
        self.assertEqual(1, len(event["outcome"]["artifact_refs"]))

    def test_raw_conversation_fields_are_rejected_at_any_depth(self):
        cases = (
            ("transcript", "synthetic transcript"),
            ("prompt", "synthetic prompt"),
            ("message", "synthetic message"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                event = valid_event()
                event["intent"][field] = value
                rendered = "\n".join(
                    MODULE.validate_interaction_event(event, f"fixture:{field}")
                )
                self.assertIn("raw conversation field", rendered)
                self.assertIn("remediation:", rendered)

    def test_direct_identifier_and_missing_artifact_are_rejected(self):
        event = valid_event()
        event["privacy"]["direct_identifiers_stored"] = True
        event["outcome"]["artifact_refs"] = []
        rendered = "\n".join(
            MODULE.validate_interaction_event(event, "fixture:privacy")
        )
        self.assertIn("direct_identifiers_stored", rendered)
        self.assertIn("artifact_refs", rendered)
        self.assertIn("remediation:", rendered)

    def test_unknown_and_duplicate_repository_snapshots_are_rejected(self):
        event = valid_event()
        event["source_snapshots"][0]["repository"] = "unknown-repository"
        event["source_snapshots"].append(copy.deepcopy(event["source_snapshots"][1]))
        rendered = "\n".join(
            MODULE.validate_interaction_event(event, "fixture:snapshots")
        )
        self.assertIn("source_snapshots[0].repository", rendered)
        self.assertIn("source_snapshots repositories must be unique", rendered)


if __name__ == "__main__":
    unittest.main()
