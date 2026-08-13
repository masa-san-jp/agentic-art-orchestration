from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.agent_ui import run_agent_ui
from tools.validate import load_json, validate_agent_ui_result


ROOT = Path(__file__).resolve().parents[1]


class AgentUIContractTests(unittest.TestCase):
    def _run(self, **overrides):
        arguments = {
            "request": load_json(ROOT / "tests/fixtures/retrieval/valid_art.json"),
            "index": load_json(ROOT / "tests/fixtures/retrieval/index.json"),
            "feedback": [
                load_json(ROOT / "tests/fixtures/feedback/valid_explicit.json"),
                load_json(ROOT / "tests/fixtures/feedback/valid_inferred.json"),
            ],
            "run_id": "AGENT-UI-001:test-contract",
            "offline_fixture": True,
            "fixture_root": Path(tempfile.mkdtemp(prefix="agent-ui-test-")),
        }
        arguments.update(overrides)
        return run_agent_ui(**arguments)

    def test_offline_command_composes_startup_retrieval_and_metadata_only_issue_plan(self):
        result = self._run()

        self.assertEqual("agent-ui/v1", result["contract_version"])
        self.assertEqual("READY_WITH_FINDINGS", result["status"])
        self.assertEqual("COMPLETE_WITH_GAPS", result["answer"]["retrieval_status"])
        self.assertTrue(all("@" in source["repository_at_commit"] for source in result["answer"]["sources"]))
        self.assertEqual("PLANNED", result["artifact"]["status"])
        self.assertEqual("PARTIAL", result["feedback"]["issue_delivery_status"])
        self.assertIn("TRIAGE", result["feedback"]["routing_statuses"])
        self.assertFalse(result["privacy"]["raw_query_stored"])
        self.assertEqual([], result["remote_operations"])
        self.assertEqual([], validate_agent_ui_result(result))

    def test_live_confirmation_is_required_and_fixture_live_is_create_read_only(self):
        with self.assertRaisesRegex(ValueError, "confirm_drive"):
            self._run(artifact_mode="live")

        result = self._run(artifact_mode="live", confirm_drive=True)
        self.assertEqual("CREATED", result["artifact"]["status"])
        self.assertEqual({"READ", "CREATE"}, {item["operation"] for item in result["remote_operations"]})
        self.assertEqual({"google-drive"}, {item["system"] for item in result["remote_operations"]})

    def test_live_lanes_cannot_be_combined(self):
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            self._run(artifact_mode="live", issue_mode="live", confirm_drive=True, confirm_issue=True)

    def test_no_artifact_mode_does_not_emit_provider_reference(self):
        result = self._run(artifact_mode="none")
        self.assertEqual("NOT_REQUESTED", result["artifact"]["status"])
        self.assertIsNone(result["artifact"]["provider_file_id"])
        self.assertEqual([], validate_agent_ui_result(result))

    def test_validator_rejects_raw_query_and_mismatched_source(self):
        result = self._run()
        altered = copy.deepcopy(result)
        altered["answer"]["sources"][0]["repository_at_commit"] = "raw query"
        altered["conversation"] = "must not be stored"
        errors = validate_agent_ui_result(altered)
        self.assertTrue(any("repository@commit" in error or "forbidden" in error for error in errors))

    def test_result_is_deterministic_and_does_not_contain_content(self):
        first = self._run()
        second = self._run()
        self.assertEqual(first, second)
        payload = json.dumps(first)
        self.assertNotIn('"content"', payload)
        self.assertNotIn('"conversation"', payload)


if __name__ == "__main__":
    unittest.main()
