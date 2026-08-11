from __future__ import annotations

import unittest

from tools.e2e import run_e2e


class EndToEndEvaluationTests(unittest.TestCase):
    def test_clean_golden_scenario_is_complete_and_traceable(self):
        result = run_e2e()

        self.assertEqual("disabled", result["network"])
        self.assertEqual("COMPLETE", result["clean"]["status"])
        self.assertTrue(result["clean"]["traceable_output"]["trace_hash"])
        self.assertEqual(3, result["clean"]["traceable_output"]["input_count"])
        self.assertEqual(3, result["clean"]["traceable_output"]["requirement_count"])
        self.assertEqual("PASSED", result["clean"]["security_status"])

    def test_each_failure_injection_has_terminal_state_and_recovery(self):
        result = run_e2e()

        failures = result["failure_injections"]
        self.assertEqual(9, len(failures))
        self.assertTrue(all(item["observed"] for item in failures))
        self.assertTrue(all(item["terminal_state"] for item in failures))
        self.assertTrue(all(item["recovery_path"] for item in failures))
        self.assertEqual(9, result["acceptance"]["failure_cases_with_terminal_state"])
        self.assertEqual(9, result["acceptance"]["failure_cases_with_recovery_path"])

    def test_safety_and_contract_failures_are_blocking_states(self):
        result = run_e2e()
        scenarios = {item["injection"]: item for item in result["failure_injections"]}

        self.assertEqual("COMPLETE_WITH_GAPS", scenarios["stale marketing signal"]["terminal_state"])
        self.assertEqual("NEEDS_REPAIR", scenarios["consumer major contract mismatch"]["terminal_state"])
        self.assertEqual("BLOCKED_HUMAN", scenarios["credential-like secret"]["terminal_state"])
        self.assertEqual("BLOCKED_HUMAN", scenarios["self-model consent violation"]["terminal_state"])

    def test_output_is_deterministic(self):
        self.assertEqual(run_e2e(), run_e2e())


if __name__ == "__main__":
    unittest.main()
