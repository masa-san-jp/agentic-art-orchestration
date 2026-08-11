from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from tools.security import audit_boundary, check_export, scan_payload


ROOT = Path(__file__).resolve().parents[1]


def valid_self() -> dict:
    return json.loads((ROOT / "tests/fixtures/signal/valid_self.json").read_text(encoding="utf-8"))


class SecurityBoundaryTests(unittest.TestCase):
    def test_clean_derived_signal_and_parent_metadata_pass(self):
        result = audit_boundary({"status": {"repository": "self-model", "source_commit": "a" * 40}}, {"valid-self": valid_self()})

        self.assertEqual("PASSED", result["status"])
        self.assertFalse(result["blocking"])

    def test_forbidden_data_is_detected_without_copying_raw_value(self):
        result = scan_payload({"PRIVATE_RAW": "sensitive raw voice body"}, "fixture")

        self.assertEqual("forbidden-data", result[0]["code"])
        rendered = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("sensitive raw voice body", rendered)

    def test_secret_is_detected_and_sanitized(self):
        result = scan_payload({"config": "token: ghp-test-secret-value"}, "fixture")

        self.assertTrue(any(finding["code"] == "secret" for finding in result))
        self.assertNotIn("ghp-test-secret-value", json.dumps(result))

    def test_unapproved_self_export_fails(self):
        signal = valid_self()
        signal["domain"]["self_model"]["export_permitted"] = False
        findings = check_export(signal, "self-model")

        self.assertTrue(any(finding["code"] == "unapproved-export" for finding in findings))

    def test_boundary_is_deterministic_and_does_not_mutate_inputs(self):
        payloads = {"b": {"value": "safe"}, "a": {"value": "safe"}}
        signals = {"s": valid_self()}
        before = copy.deepcopy([payloads, signals])
        first = audit_boundary(payloads, signals)
        second = audit_boundary(payloads, signals)

        self.assertEqual(first, second)
        self.assertEqual(before, [payloads, signals])


if __name__ == "__main__":
    unittest.main()
