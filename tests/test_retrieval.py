from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from tools.retrieval import RetrievalError, route_query
from tools.validate import load_yaml, validate_retrieval_index, validate_retrieval_request, validate_retrieval_result


ROOT = Path(__file__).resolve().parents[1]


def fixture(name: str) -> dict:
    with (ROOT / "tests/fixtures/retrieval" / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def manifest() -> dict:
    return load_yaml(ROOT / "config/repositories.yaml")


class RetrievalTests(unittest.TestCase):
    def test_domain_query_selects_minimum_child_and_returns_immutable_evidence(self):
        request = fixture("valid_art.json")
        result = route_query(request, fixture("index.json"), manifest())

        self.assertEqual("COMPLETE_WITH_GAPS", result["status"])
        self.assertEqual(["art-history"], [item["repository"] for item in result["selected_repositories"]])
        self.assertEqual(["art-history"], sorted({item["repository"] for item in result["evidence"]}))
        self.assertTrue(result["evidence"])
        self.assertEqual(
            manifest()["repositories"][1]["observed_commit"],
            result["selected_repositories"][0]["source_commit"],
        )
        for evidence in result["evidence"]:
            self.assertEqual("art-history", evidence["repository"])
            self.assertEqual("de5a3c3ef2d1cb13f84e522ee73211d70e214f65", evidence["source_commit"])
            self.assertTrue(evidence["locator"])
        self.assertFalse(result["interaction_blocking"])
        self.assertEqual([], result["retrieval_operations"])
        self.assertFalse(result["privacy"]["raw_query_stored"])
        self.assertEqual([], validate_retrieval_result(result, manifest(), request))

    def test_minimum_relevant_set_covers_multiple_domains_without_fetching_self_model(self):
        request = fixture("valid_art.json")
        request["request_id"] = "request:portfolio-art-and-freshness"
        request["capability_codes"] = ["art-history", "freshness"]
        result = route_query(request, fixture("index.json"), manifest())

        self.assertEqual(["art-history", "marketing-trends"], [item["repository"] for item in result["selected_repositories"]])
        self.assertNotIn("self-model", {item["repository"] for item in result["selected_repositories"]})
        self.assertEqual({"art-history", "marketing-trends"}, {item["repository"] for item in result["evidence"]})
        self.assertEqual([], validate_retrieval_result(result, manifest(), request))

    def test_stale_freshness_and_unknowns_are_preserved(self):
        request = fixture("valid_art.json")
        request["request_id"] = "request:marketing-freshness"
        request["capability_codes"] = ["marketing-trends", "freshness"]
        result = route_query(request, fixture("index.json"), manifest())

        self.assertEqual("stale", result["evidence"][0]["freshness_status"])
        self.assertIn("freshness-revalidation-required:marketing-trends", result["unknowns"])
        self.assertIn("Revalidate freshness before treating this trend as current.", result["domain_constraints"])
        self.assertEqual("COMPLETE_WITH_GAPS", result["status"])

    def test_current_only_does_not_normalize_stale_entry(self):
        request = fixture("valid_art.json")
        request["request_id"] = "request:marketing-current-only"
        request["capability_codes"] = ["marketing-trends"]
        request["freshness_preference"] = "current-only"
        result = route_query(request, fixture("index.json"), manifest())

        self.assertEqual("NO_MATCH", result["status"])
        self.assertEqual([], result["selected_repositories"])
        self.assertEqual([], result["evidence"])
        self.assertIn("capability-unmatched:marketing-trends", result["unknowns"])

    def test_unmatched_capability_is_explicit_gap(self):
        request = fixture("valid_art.json")
        request["request_id"] = "request:unknown-capability"
        request["capability_codes"] = ["unmapped-capability"]
        result = route_query(request, fixture("index.json"), manifest())

        self.assertEqual("NO_MATCH", result["status"])
        self.assertEqual(["capability-unmatched:unmapped-capability"], result["unknowns"])

    def test_index_commit_mismatch_is_rejected_before_retrieval(self):
        index = fixture("index.json")
        index["entries"][0]["source_commit"] = "0" * 40
        with self.assertRaisesRegex(RetrievalError, "manifest observed commit"):
            route_query(fixture("valid_art.json"), index, manifest())

    def test_unknown_repository_in_index_is_rejected(self):
        index = fixture("index.json")
        index["entries"][0]["repository"] = "unregistered"
        with self.assertRaisesRegex(RetrievalError, "unknown repository"):
            route_query(fixture("valid_art.json"), index, manifest())

    def test_raw_query_and_input_mutation_are_rejected(self):
        request = fixture("valid_art.json")
        index = fixture("index.json")
        before_request = copy.deepcopy(request)
        before_index = copy.deepcopy(index)
        first = route_query(request, index, manifest(), "RETRIEVAL-001:deterministic")
        second = route_query(request, index, manifest(), "RETRIEVAL-001:deterministic")

        self.assertEqual(first, second)
        self.assertEqual(before_request, request)
        self.assertEqual(before_index, index)
        self.assertNotIn('"query"', json.dumps(first))

        request["query"] = "raw conversational wording must not enter the contract"
        with self.assertRaisesRegex(RetrievalError, "forbidden raw or sensitive retrieval field"):
            route_query(request, index, manifest())

    def test_contract_validators_cover_request_index_and_result(self):
        request = fixture("valid_art.json")
        index = fixture("index.json")
        result = route_query(request, index, manifest())

        self.assertEqual([], validate_retrieval_request(request, manifest=manifest()))
        self.assertEqual([], validate_retrieval_index(index, manifest()))
        self.assertEqual([], validate_retrieval_result(result, manifest(), request))

        schema = json.loads((ROOT / "schemas/retrieval-result.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("retrieval-result/v1", schema["properties"]["contract_version"]["const"])
        self.assertEqual("FRONTSTAGE_RETRIEVAL", schema["properties"]["lane"]["const"])
        self.assertEqual([], schema["properties"]["retrieval_operations"]["const"])


if __name__ == "__main__":
    unittest.main()
