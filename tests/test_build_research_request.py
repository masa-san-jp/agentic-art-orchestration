from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("orchestration_request", ROOT / "tools/build_research_request.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _signal(signal_id: str, kind: str, domain: dict, entity: str) -> dict:
    return {
        "signal_id": signal_id,
        "signal_kind": kind,
        "statement": f"{signal_id} の要約",
        "source": {"repository": kind if kind != "self" else "self-model", "commit": "a" * 40, "entity_ids": [entity]},
        "evidence_refs": [{"locator": "entities/x.md#evidence", "kind": "derived"}],
        "unknowns": [f"{signal_id} の未取得事項"],
        "domain": domain,
    }


PROPOSITION = {
    "proposition_id": "proposition:abc",
    "structured_output": {
        "template": "{personal_tension} is externalized through {historical_operation} against {contemporary_condition}",
        "slots": {
            "personal_tension": {"signal_id": "self:masa", "signal_kind": "self", "attribute": "tensions"},
            "historical_operation": {"signal_id": "art-history:x", "signal_kind": "art-history", "attribute": "relations"},
            "contemporary_condition": {"signal_id": "marketing:y", "signal_kind": "marketing", "attribute": "stage"},
        },
    },
}

SIGNALS = {
    "self:masa": _signal("self:masa", "self", {"self_model": {"tensions": ["近いのに届かない"]}}, "subject/masa"),
    "art-history:x": _signal(
        "art-history:x", "art-history",
        {"art_history": {"relations": [{"relation": "influenced_by", "target_entity_id": "movement/b"}]}},
        "movement/a",
    ),
    "marketing:y": _signal("marketing:y", "marketing", {"marketing": {"stage": "growing"}}, "trend/y"),
}


class CreativeQuestionTests(unittest.TestCase):
    def test_question_uses_the_bound_attribute_not_the_record_summary(self):
        question = MODULE._creative_question(PROPOSITION, SIGNALS)

        self.assertIn("近いのに届かない", question)
        self.assertNotIn("の要約", question)

    def test_relation_names_the_entities_it_connects(self):
        question = MODULE._creative_question(PROPOSITION, SIGNALS)

        self.assertIn("movement/a", question)
        self.assertIn("movement/b", question)


class BoundaryTests(unittest.TestCase):
    def _request(self) -> dict:
        return MODULE.build_request(
            PROPOSITION, SIGNALS, request_id="RR001", slug="s", title="t",
            requested_at="2026-08-20T07:00:00+09:00", commit="b" * 40, deadline=None, creator_id=None,
            full_names={"self-model": "masa-san-jp/self-model-notes"},
        )

    def test_personal_input_keeps_the_request_project_internal(self):
        request = self._request()

        self.assertEqual("PROJECT_INTERNAL", request["constraints"]["publication_scope"])
        self.assertEqual("PRIVATE_DERIVED", request["data_boundary"]["classification"])

    def test_raw_data_is_never_carried(self):
        self.assertFalse(self._request()["data_boundary"]["raw_data_included"])

    def test_every_outward_action_is_prohibited_at_research_time(self):
        request = self._request()

        for action in ("publish", "submit", "send", "purchase", "contract", "delete"):
            self.assertIn(action, request["constraints"]["prohibited_actions"])

    def test_undecided_fields_are_empty_rather_than_guessed(self):
        request = self._request()

        self.assertIsNone(request["intent"]["audience_experience"])
        self.assertEqual([], request["intent"]["medium_materials"])
        self.assertIsNone(request["constraints"]["budget"])

    def test_unknowns_from_every_used_signal_become_open_questions(self):
        questions = self._request()["open_questions"]

        self.assertEqual(3, len(questions))

    def test_reference_uri_is_pinned_to_the_commit_it_came_from(self):
        uri = MODULE._reference_uri(SIGNALS["self:masa"], "entities/x.md", {"self-model": "masa-san-jp/self-model-notes"})

        self.assertEqual("https://github.com/masa-san-jp/self-model-notes/blob/" + "a" * 40 + "/entities/x.md", uri)


if __name__ == "__main__":
    unittest.main()
