import unittest

from tools.element_checks import check_value


def failures(text):
    return [item["check"] for item in check_value(text, ["one_sentence"], inputs={}, ledger={}, previous_answers={}) or []]


class OneSentenceQuoteTests(unittest.TestCase):
    def test_marks_inside_quotes_or_embedded_english_do_not_split(self):
        self.assertEqual([], failures("本人の悩みに、idea or concept is the most important aspect of the work.という考えが答えを与える。"))
        self.assertEqual([], failures("「確定を待つ。」という態度に、規則が答えを与える。"))

    def test_two_outer_sentences_still_fail(self):
        self.assertIn("one_sentence", failures("本人は確定を待つ。規則が答えを与える。"))
        self.assertIn("one_sentence", failures("It waits. The rule answers."))


if __name__ == "__main__":
    unittest.main()
