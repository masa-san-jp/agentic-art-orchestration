from __future__ import annotations

import unittest

from tools.legacy_plan_recovery import REFERENCE_CATEGORIES, make_source_ref_index


class LegacyPlanRecoveryTests(unittest.TestCase):
    def test_source_index_reports_missing_categories_and_no_public_urls(self):
        index = make_source_ref_index("P0001", "plans/P0001-owner-of-choice", "a" * 64, "b" * 64)

        self.assertEqual("project/legacy-recovery-p0001", index["source_project"])
        self.assertEqual(list(REFERENCE_CATEGORIES), [item["category"] for item in index["category_access"]])
        self.assertTrue(all("access_url" not in reference for reference in index["references"]))
        self.assertNotIn("github.com/masa-san-jp/agentic-art-project", str(index))
        self.assertEqual(
            {"DC001": "INTERNAL_RECORD", "IN001": "INTERNAL_RECORD"},
            {reference["id"]: reference["access_url_reason"] for reference in index["references"]},
        )

        by_category = {item["category"]: item for item in index["category_access"]}
        self.assertEqual(["DC001"], by_category["CONCEPT"]["source_ref_ids"])
        self.assertEqual("SOURCE_HAS_NO_PUBLIC_URL", by_category["CONCEPT"]["reason_code"])
        self.assertEqual([], by_category["VISUAL"]["source_ref_ids"])
        self.assertEqual("NO_SOURCE_FOR_CATEGORY", by_category["VISUAL"]["reason_code"])
        self.assertEqual(["IN001"], by_category["METHOD"]["source_ref_ids"])
        self.assertEqual("SOURCE_HAS_NO_PUBLIC_URL", by_category["METHOD"]["reason_code"])


if __name__ == "__main__":
    unittest.main()
