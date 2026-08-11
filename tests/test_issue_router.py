from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from tools.issue_router import IssueRouterError, route_feedback
from tools.validate import load_yaml, validate_issue_routing


ROOT = Path(__file__).resolve().parents[1]


def feedback(name: str) -> dict:
    with (ROOT / "tests/fixtures/feedback" / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def manifest() -> dict:
    return load_yaml(ROOT / "config/repositories.yaml")


class IssueRouterTests(unittest.TestCase):
    def test_explicit_confirmed_domain_feedback_routes_to_child(self):
        signal = feedback("valid_explicit.json")
        result = route_feedback([signal], manifest())
        route = result["routes"][0]

        self.assertEqual("ROUTED", route["routing_status"])
        self.assertEqual("art-history", route["target_repository"])
        self.assertEqual("CHILD", route["target_role"])
        self.assertTrue(route["issue_candidate"]["creation_permitted"])
        self.assertTrue(route["issue_candidate"]["human_gate"])
        self.assertEqual([], result["issue_operations"])
        self.assertEqual([], validate_issue_routing(result))

    def test_medium_inferred_feedback_remains_triage_and_unconfirmed(self):
        signal = feedback("valid_inferred.json")
        result = route_feedback([signal], manifest())
        route = result["routes"][0]

        self.assertEqual("TRIAGE", route["routing_status"])
        self.assertIsNone(route["target_repository"])
        self.assertEqual("TRIAGE", route["target_role"])
        self.assertFalse(route["issue_candidate"]["creation_permitted"])
        self.assertEqual("unconfirmed", route["inference"]["hypothesis_status"])
        self.assertEqual([], validate_issue_routing(result))

    def test_high_inferred_feedback_can_route_without_promoting_user_fact(self):
        signal = feedback("valid_inferred.json")
        signal["target"]["routing_status"] = "confirmed"
        signal["confidence"] = {"level": "high", "score": 0.9}
        result = route_feedback([signal], manifest())
        route = result["routes"][0]

        self.assertEqual("ROUTED", route["routing_status"])
        self.assertEqual("agentic-art-orchestration", route["target_repository"])
        self.assertTrue(route["issue_candidate"]["creation_permitted"])
        self.assertTrue(route["inference"]["is_inferred"])
        self.assertEqual("unconfirmed", route["inference"]["hypothesis_status"])
        self.assertEqual([], validate_issue_routing(result))

    def test_duplicate_issue_key_is_suppressed_deterministically(self):
        first = feedback("valid_explicit.json")
        second = copy.deepcopy(first)
        second["feedback_id"] = "feedback:interaction-001:003"
        reversed_inputs = [second, first]

        result = route_feedback(reversed_inputs, manifest())
        routes = {route["feedback_id"]: route for route in result["routes"]}
        canonical = routes[first["feedback_id"]]
        suppressed = routes[second["feedback_id"]]

        self.assertEqual("ROUTED", canonical["routing_status"])
        self.assertEqual("DUPLICATE_SUPPRESSED", suppressed["routing_status"])
        self.assertEqual(
            sorted([first["feedback_id"], second["feedback_id"]]),
            canonical["issue_candidate"]["source_feedback_ids"],
        )
        self.assertEqual(first["feedback_id"], result["duplicate_suppressions"][0]["canonical_feedback_id"])
        self.assertEqual([], validate_issue_routing(result))

    def test_candidate_or_conflicting_authority_remains_triageable(self):
        candidate = feedback("valid_explicit.json")
        candidate["target"]["routing_status"] = "candidate"
        candidate_result = route_feedback([candidate], manifest())
        self.assertEqual("TRIAGE", candidate_result["routes"][0]["routing_status"])
        self.assertEqual(["art-history"], candidate_result["routes"][0]["candidate_repositories"])

        conflict = feedback("valid_explicit.json")
        conflict["target"]["owner_repository"] = "self-model"
        conflict_result = route_feedback([conflict], manifest())
        conflict_route = conflict_result["routes"][0]
        self.assertEqual("TRIAGE", conflict_route["routing_status"])
        self.assertEqual(["art-history", "self-model"], conflict_route["candidate_repositories"])
        self.assertEqual([], validate_issue_routing(conflict_result))

    def test_consent_denial_blocks_without_issue_candidate(self):
        signal = feedback("valid_explicit.json")
        signal["consent"]["issue_creation_permitted"] = False
        result = route_feedback([signal], manifest())
        route = result["routes"][0]

        self.assertEqual("BLOCKED", route["routing_status"])
        self.assertIsNone(route["issue_candidate"])
        self.assertEqual([], result["issue_operations"])
        self.assertEqual([], validate_issue_routing(result))

    def test_determinism_input_immutability_and_raw_feedback_rejection(self):
        signals = [feedback("valid_explicit.json"), feedback("valid_inferred.json")]
        before = copy.deepcopy(signals)
        first = route_feedback(signals, manifest(), "ISSUE-ROUTER-001:deterministic")
        second = route_feedback(signals, manifest(), "ISSUE-ROUTER-001:deterministic")

        self.assertEqual(first, second)
        self.assertEqual(before, signals)
        self.assertNotIn("message", json.dumps(first))

        invalid = feedback("valid_explicit.json")
        invalid["message"] = "raw feedback must remain outside the route"
        with self.assertRaisesRegex(IssueRouterError, "forbidden raw feedback field"):
            route_feedback([invalid], manifest())

    def test_schema_declares_metadata_only_feedback_routing(self):
        schema = json.loads((ROOT / "schemas/issue-routing.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("issue-routing/v1", schema["properties"]["contract_version"]["const"])
        self.assertEqual("FEEDBACK_ROUTING", schema["properties"]["lane"]["const"])
        self.assertEqual([], schema["properties"]["issue_operations"]["const"])
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
