from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
import tempfile

from tools.agent_ui import run_agent_ui
from tools.input_pipeline import run_input_pipeline
from tools.inspiration import capture_inspiration, settle_inspiration
from tools.retrieval import route_query
from tools.signal_bundle import build_signal_bundle
from tools.validate import load_json, load_yaml, validate_inspiration


ROOT = Path(__file__).resolve().parents[1]


def signals() -> list[dict]:
    return [
        load_json(ROOT / "tests/fixtures/signal" / name)
        for name in ("valid_self.json", "valid_art_history.json", "valid_marketing.json")
    ]


class InspirationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = load_json(ROOT / "tests/fixtures/retrieval/valid_art.json")
        index = load_json(ROOT / "tests/fixtures/retrieval/index.json")
        self.retrieval = route_query(self.request, index, load_yaml(ROOT / "config/repositories.yaml"), "INSPIRATION-001:test-retrieval")
        self.bundle = build_signal_bundle(signals(), "2026-08-11T21:00:00+09:00")

    def capture(self) -> dict:
        return capture_inspiration(
            self.request,
            self.retrieval,
            run_id="INSPIRATION-001:test",
            inspiration={"goal_code": "explore-relations"},
        )

    def test_capture_is_structured_and_preserves_retrieval_provenance(self):
        captured = self.capture()

        self.assertEqual("inspiration-input/v1", captured["contract_version"])
        self.assertEqual("CAPTURED", captured["phase"])
        self.assertEqual("explore-relations", captured["capture"]["intent"]["goal_code"])
        self.assertEqual(["art-history"], [item["repository"] for item in captured["provenance"]["retrieval_source_snapshots"]])
        self.assertFalse(captured["privacy"]["raw_inspiration_stored"])
        self.assertFalse(captured["privacy"]["raw_conversation_stored"])
        self.assertEqual([], validate_inspiration(captured))

    def test_settlement_reaches_candidate_pipeline_with_complete_provenance(self):
        captured = self.capture()
        pipeline = run_input_pipeline(
            self.bundle,
            project_id="inspiration-project",
            seed_input="inspiration",
            inspiration=captured,
        )
        settled = pipeline["inspiration"]

        self.assertEqual("SETTLED", settled["phase"])
        self.assertEqual("research-candidate/v1", settled["settlement"]["candidate_pipeline"])
        self.assertEqual(1, len(settled["settlement"]["selected_candidate_ids"]))
        self.assertEqual(3, len(settled["provenance"]["pipeline_source_snapshots"]))
        self.assertTrue(settled["provenance"]["candidate_input_refs"])
        self.assertTrue(settled["consent"]["settlement_confirmed"])
        self.assertEqual([], validate_inspiration(settled))

    def test_same_run_is_deterministic_and_contains_no_raw_text(self):
        first = run_input_pipeline(self.bundle, project_id="inspiration-project", seed_input="inspiration", inspiration=self.capture())
        second = run_input_pipeline(self.bundle, project_id="inspiration-project", seed_input="inspiration", inspiration=self.capture())

        self.assertEqual(first["inspiration"], second["inspiration"])
        rendered = json.dumps(first["inspiration"], ensure_ascii=False)
        self.assertNotIn('"conversation":', rendered)
        self.assertNotIn('"raw_text":', rendered)
        self.assertNotIn('"statement":', rendered)

    def test_raw_or_changed_provenance_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            capture_inspiration(self.request, self.retrieval, inspiration={"goal_code": "explore-relations", "text": "raw"})

        captured = self.capture()
        altered_retrieval = copy.deepcopy(self.retrieval)
        altered_retrieval["selected_repositories"][0]["source_commit"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "retrieval provenance"):
            capture_inspiration(self.request, altered_retrieval, run_id="INSPIRATION-001:changed")

    def test_settlement_rejects_tampered_pipeline_and_no_candidate(self):
        captured = self.capture()
        pipeline = run_input_pipeline(self.bundle, project_id="inspiration-project", seed_input="inspiration")
        altered = copy.deepcopy(pipeline)
        altered["selection"]["candidate_space_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hashes do not match"):
            settle_inspiration(captured, altered)

        altered = copy.deepcopy(pipeline)
        altered["selection"]["selected_candidates"] = []
        altered["selection"]["selected_count"] = 0
        with self.assertRaises(ValueError):
            settle_inspiration(captured, altered)

    def test_agent_ui_captures_and_settles_inspiration(self):
        result = run_agent_ui(
            request=self.request,
            index=load_json(ROOT / "tests/fixtures/retrieval/index.json"),
            feedback=[load_json(ROOT / "tests/fixtures/feedback/valid_explicit.json")],
            run_id="INSPIRATION-001:agent-ui",
            offline_fixture=True,
            fixture_root=Path(tempfile.mkdtemp(prefix="inspiration-agent-ui-")),
            inspiration={"goal_code": "explore-relations"},
            signal_bundle=self.bundle,
            artifact_mode="none",
        )

        self.assertEqual("SETTLED", result["inspiration"]["status"])
        self.assertEqual(1, len(result["inspiration"]["selected_candidate_ids"]))
        self.assertFalse(result["inspiration"]["privacy"]["raw_inspiration_stored"])
        self.assertNotIn('"conversation":', json.dumps(result))


if __name__ == "__main__":
    unittest.main()
