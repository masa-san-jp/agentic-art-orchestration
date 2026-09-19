import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import knowledge_cycle_run as cycle


class ThemeResearchWordingTest(unittest.TestCase):
    """orchestration#251: the art-history write-job request names the theme-research completion condition."""

    def test_art_history_request_names_pass_and_reason_contents(self):
        text = cycle.write_job_action('art-history-notes')
        self.assertIn('theme research pass', text)
        self.assertIn('theme_research_pass.py write-job', text)
        self.assertIn('no-new-evidence', text)
        self.assertIn('hit_count', text)
        self.assertIn('budget', text)
        self.assertTrue(text.startswith(cycle.WRITE_JOB_ACTION))

    def test_parent_never_prescribes_search_terms_or_sources(self):
        text = cycle.write_job_action('art-history-notes')
        for forbidden in ('--theme', 'wikipedia', 'search for'):
            self.assertNotIn(forbidden, text.lower())

    def test_other_owners_keep_the_generic_request(self):
        for owner in cycle.OWNERS:
            if owner != 'art-history-notes':
                self.assertEqual(cycle.WRITE_JOB_ACTION, cycle.write_job_action(owner))


if __name__ == '__main__':
    unittest.main()
