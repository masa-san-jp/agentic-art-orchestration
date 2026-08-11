from __future__ import annotations

import unittest

from tests.fixtures.build_fixture import build_fixture


class FixtureBuilderTests(unittest.TestCase):
    def test_four_repository_failure_fixture_is_complete_and_deterministic(self):
        first = build_fixture()
        second = build_fixture()

        self.assertEqual(first, second)
        self.assertEqual(4, len(first["repositories"]))
        self.assertEqual("disabled", first["network"])
        self.assertTrue(all(scenario["observed"] for scenario in first["scenarios"].values()))
        self.assertTrue(first["audit_non_blocking"])


if __name__ == "__main__":
    unittest.main()
