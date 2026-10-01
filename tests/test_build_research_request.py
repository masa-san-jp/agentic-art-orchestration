from __future__ import annotations

import hashlib
import importlib.util
import json
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


def _anchor_id(signal_id: str, attribute: str, value: str) -> str:
    payload = f"{signal_id}\n{attribute}\n{json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


MULTI_TENSION_SIGNAL = _signal(
    "self:masa",
    "self",
    {"self_model": {"tensions": ["近いのに届かない", "別の緊張"]}},
    "subject/masa",
)
MULTI_TENSION_SIGNALS = {**SIGNALS, "self:masa": MULTI_TENSION_SIGNAL}


def _proposition_with_anchor(anchor_id: str | None) -> dict:
    proposition = {
        "proposition_id": "proposition:abc",
        "structured_output": {
            "template": "{personal_tension} is externalized through {historical_operation} against {contemporary_condition}",
            "slots": {
                "personal_tension": {
                    "signal_id": "self:masa",
                    "signal_kind": "self",
                    "attribute": "tensions",
                    **({"anchor_id": anchor_id} if anchor_id is not None else {}),
                },
                "historical_operation": {"signal_id": "art-history:x", "signal_kind": "art-history", "attribute": "relations"},
                "contemporary_condition": {"signal_id": "marketing:y", "signal_kind": "marketing", "attribute": "stage"},
            },
        },
    }
    return proposition


class CreativeQuestionTests(unittest.TestCase):
    def test_question_uses_the_bound_attribute_not_the_record_summary(self):
        question = MODULE._creative_question(PROPOSITION, SIGNALS)

        self.assertIn("近いのに届かない", question)
        self.assertNotIn("の要約", question)

    def test_relation_names_the_entities_it_connects(self):
        question = MODULE._creative_question(PROPOSITION, SIGNALS)

        self.assertIn("movement/a", question)
        self.assertIn("movement/b", question)

    def test_different_anchors_yield_different_questions(self):
        """Two candidates differing only in which tension anchor they bind
        must produce different creative_question text. Before this fix,
        _bound_value always read value[0] regardless of which anchor the
        candidate actually used, so distinct lineages collapsed onto the
        same wording.
        """
        first_anchor = _anchor_id("self:masa", "tensions", "近いのに届かない")
        second_anchor = _anchor_id("self:masa", "tensions", "別の緊張")

        first_question = MODULE._creative_question(_proposition_with_anchor(first_anchor), MULTI_TENSION_SIGNALS)
        second_question = MODULE._creative_question(_proposition_with_anchor(second_anchor), MULTI_TENSION_SIGNALS)

        self.assertIn("近いのに届かない", first_question)
        self.assertIn("別の緊張", second_question)
        self.assertNotEqual(first_question, second_question)

    def test_missing_anchor_id_falls_back_to_the_first_value(self):
        question = MODULE._creative_question(_proposition_with_anchor(None), MULTI_TENSION_SIGNALS)

        self.assertIn("近いのに届かない", question)


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


class RequestIdentityTests(unittest.TestCase):
    def _accepted_project(self, research_root: Path, slug: str, request_id: str) -> None:
        intake = research_root / "projects" / slug / "00_intake"
        intake.mkdir(parents=True, exist_ok=True)
        (intake / "research-request.yaml").write_text(
            f"request_id: {request_id}\nproject:\n  slug: {slug}\n", encoding="utf-8"
        )

    def test_next_id_skips_requests_already_accepted_by_research(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "requests"
            output.mkdir()
            research_root = root / "research"
            self._accepted_project(research_root, "harmony-proof", "RR001")
            self._accepted_project(research_root, "probe-unattended", "RR002")

            self.assertEqual("RR003", MODULE._next_request_id(output, research_root=research_root))

    def test_next_id_counts_this_run_and_research_together(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "requests"
            output.mkdir()
            (output / "RR004.yaml").write_text("request_id: RR004\n", encoding="utf-8")
            research_root = root / "research"
            self._accepted_project(research_root, "harmony-proof", "RR001")

            self.assertEqual("RR005", MODULE._next_request_id(output, research_root=research_root))

    def test_without_research_root_preserves_legacy_run_local_allocation(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "requests"
            output.mkdir()

            self.assertEqual("RR001", MODULE._next_request_id(output))


if __name__ == "__main__":
    unittest.main()
