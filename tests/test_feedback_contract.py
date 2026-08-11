from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("orchestration_validate", ROOT / "tools/validate.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def fixture(name: str) -> dict:
    with (ROOT / "tests/fixtures/feedback" / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class FeedbackContractTests(unittest.TestCase):
    def test_explicit_and_inferred_fixtures_are_valid_and_unchanged(self):
        for name in ("valid_explicit.json", "valid_inferred.json"):
            with self.subTest(name=name):
                signal = fixture(name)
                original = copy.deepcopy(signal)
                self.assertEqual([], MODULE.validate_feedback_signal(signal, f"fixture:{name}"))
                self.assertEqual(original, signal)

    def test_inferred_feedback_requires_unconfirmed_hypothesis_and_non_explicit_confidence(self):
        signal = fixture("valid_inferred.json")
        signal["hypothesis"] = None
        signal["confidence"] = {"level": "explicit", "score": 1.0}
        rendered = "\n".join(MODULE.validate_feedback_signal(signal, "fixture:inferred"))
        self.assertIn("inferred feedback requires a hypothesis", rendered)
        self.assertIn("cannot use explicit confidence", rendered)

    def test_explicit_feedback_cannot_carry_inferred_hypothesis(self):
        signal = fixture("valid_explicit.json")
        signal["hypothesis"] = fixture("valid_inferred.json")["hypothesis"]
        signal["confidence"] = {"level": "medium", "score": 0.6}
        rendered = "\n".join(MODULE.validate_feedback_signal(signal, "fixture:explicit"))
        self.assertIn("explicit feedback must not carry an inferred hypothesis", rendered)
        self.assertIn("explicit confidence", rendered)

    def test_inference_cannot_be_promoted_to_user_fact_or_profile_update(self):
        signal = fixture("valid_inferred.json")
        signal["promoted_to_user_fact"] = True
        signal["consent"]["profile_update_permitted"] = True
        rendered = "\n".join(MODULE.validate_feedback_signal(signal, "fixture:promotion"))
        self.assertIn("promoted_to_user_fact", rendered)
        self.assertIn("profile_update_permitted", rendered)

    def test_unknown_target_and_raw_feedback_text_are_rejected(self):
        signal = fixture("valid_inferred.json")
        signal["target"]["owner_repository"] = "unknown-repository"
        signal["message"] = "synthetic raw feedback"
        rendered = "\n".join(MODULE.validate_feedback_signal(signal, "fixture:target"))
        self.assertIn("owner_repository", rendered)
        self.assertIn("forbidden raw feedback field", rendered)
        self.assertIn("remediation:", rendered)


if __name__ == "__main__":
    unittest.main()
