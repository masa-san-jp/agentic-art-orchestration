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


VALID = {
    "contract_version": "research-signal-export/v1",
    "source_repository": "art-history",
    "source_commit": "0" * 40,
    "purpose": "artistic-research",
    "generated_at": "2026-08-19T17:00:00+09:00",
    "signal_count": 2,
    "signals": [{"signal_id": "art-history:mannerism"}, {"signal_id": "art-history:baroque"}],
}


class SignalExportEnvelopeTests(unittest.TestCase):
    def test_declared_envelope_passes(self):
        self.assertEqual([], MODULE.validate_signal_export(VALID, "fixture:valid"))

    def test_count_must_match_the_records_carried(self):
        payload = copy.deepcopy(VALID)
        payload["signal_count"] = 7

        errors = MODULE.validate_signal_export(payload, "fixture:count")
        rendered = "\n".join(errors)

        self.assertIn("does not match", rendered)
        self.assertIn("remediation:", rendered)

    def test_repeated_signal_id_is_rejected(self):
        payload = copy.deepcopy(VALID)
        payload["signals"][1]["signal_id"] = payload["signals"][0]["signal_id"]

        errors = MODULE.validate_signal_export(payload, "fixture:duplicate")

        self.assertTrue(any("appears more than once" in error for error in errors))

    def test_unknown_source_repository_is_rejected(self):
        payload = copy.deepcopy(VALID)
        payload["source_repository"] = "some-other-notes"

        self.assertTrue(MODULE.validate_signal_export(payload, "fixture:source"))

    def test_short_commit_is_rejected(self):
        payload = copy.deepcopy(VALID)
        payload["source_commit"] = "abc1234"

        self.assertTrue(MODULE.validate_signal_export(payload, "fixture:commit"))

    def test_every_manifest_input_repository_is_an_allowed_source(self):
        manifest = MODULE.load_yaml(ROOT / "config/repositories.yaml")
        schema = MODULE.load_json(ROOT / "schemas/research-signal-export.schema.json")
        allowed = set(schema["properties"]["source_repository"]["enum"])
        inputs = {
            repository["id"]
            for repository in manifest["repositories"]
            if repository.get("role") == "input-kb" and repository["id"] in {"self-model", "art-history", "marketing-trends"}
        }

        self.assertEqual(inputs, allowed)

    def test_records_are_not_judged_here(self):
        """Each kind has its own shape; the adapters translate them at the boundary."""
        payload = copy.deepcopy(VALID)
        payload["signals"][0]["whatever_the_kind_needs"] = {"nested": True}

        self.assertEqual([], MODULE.validate_signal_export(payload, "fixture:opaque"))


if __name__ == "__main__":
    unittest.main()
