from __future__ import annotations

from pathlib import Path
import unittest

from tools.autonomous_runner import _new_state, validate_autonomous_state
from tools.delivery_completion import completion, normal_contract, resolve_contract, validate_contract
from tools.validate import load_json, validate_delivery_contract_schema


class AutonomousPlanContractTests(unittest.TestCase):
    def test_delivery_contract_is_closed_and_versioned(self):
        schema = load_json(Path("schemas/delivery-contract.schema.json"))
        self.assertEqual([], validate_delivery_contract_schema(schema))
        self.assertEqual([], validate_contract({"contract_version": "delivery-contract/v1", "target": "project-local"}))

        extra = {"contract_version": "delivery-contract/v1", "target": "project-local", "approval": True}
        self.assertTrue(validate_contract(extra))
        self.assertTrue(validate_contract({"contract_version": "delivery-contract/v2", "target": "project-local"}))

    def test_new_and_legacy_resolution_have_distinct_meanings(self):
        internal = {"delivery_mode": "internal", "permissions": {"public_projection": False}}
        public = {"delivery_mode": "public-catalog", "permissions": {"public_projection": True}}
        self.assertEqual("internal", normal_contract(internal)["target"])
        self.assertEqual("project-local", normal_contract(public)["target"])
        self.assertEqual("project-local", resolve_contract(None, public)["target"])
        self.assertEqual("project-committed", resolve_contract(None, public, legacy_context=True)["target"])
        with self.assertRaisesRegex(ValueError, "DELIVERY_PROFILE_MISMATCH"):
            resolve_contract({"contract_version": "delivery-contract/v1", "target": "project-local"}, internal)

    def test_supervisor_state_carries_the_same_contract(self):
        state = _new_state(
            "contract-run",
            "agentic-art-research",
            "a" * 40,
            "project",
            ["project"],
            "2026-09-12T00:00:00Z",
            {"contract_version": "delivery-contract/v1", "target": "internal"},
        )
        self.assertEqual([], validate_autonomous_state(state))
        self.assertEqual("internal", state["delivery_contract"]["target"])

    def test_completion_requires_each_requested_delivery_stage(self):
        state = {
            "plan_status": "PLAN_READY",
            "plan": {
                "artifacts": {"03_plan/production-plan.md": "a" * 64},
                "owner_verification": {"plan_status": "PLAN_READY"},
            },
            "knowledge_status": "COMMITTED",
            "projection_status": "SKIPPED",
        }
        self.assertEqual("COMPLETED", completion(state, {"contract_version": "delivery-contract/v1", "target": "internal"})["status"])
        local = completion(state, {"contract_version": "delivery-contract/v1", "target": "project-local"})
        self.assertEqual("INCOMPLETE", local["status"])
        self.assertIn("PROJECT_LOCAL_DELIVERY", local["missing"])


if __name__ == "__main__":
    unittest.main()
