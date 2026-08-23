import unittest

from robbie.review import parse_grade


class TestParseGrade(unittest.TestCase):
    def test_letters(self):
        self.assertEqual(parse_grade("a"), "again")
        self.assertEqual(parse_grade("H"), "hard")
        self.assertEqual(parse_grade("g"), "good")
        self.assertEqual(parse_grade("e"), "easy")

    def test_numbers(self):
        self.assertEqual(parse_grade("1"), "again")
        self.assertEqual(parse_grade("2"), "hard")
        self.assertEqual(parse_grade("3"), "good")
        self.assertEqual(parse_grade("4"), "easy")

    def test_whitespace_ok(self):
        self.assertEqual(parse_grade("  g  "), "good")

    def test_unknown_returns_none(self):
        self.assertIsNone(parse_grade("x"))
        self.assertIsNone(parse_grade(""))
        self.assertIsNone(parse_grade("5"))


if __name__ == "__main__":
    unittest.main()
