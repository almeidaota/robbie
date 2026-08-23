import unittest
from datetime import date

from robbie.sm2 import CardState, card_slug


class TestCardSlug(unittest.TestCase):
    def test_lowercases_and_strips(self):
        self.assertEqual(card_slug("Substituir", "Replace"), "substituir->replace")

    def test_collapses_inner_whitespace(self):
        self.assertEqual(card_slug("  atualize  ", " update "), "atualize->update")


class TestReview(unittest.TestCase):
    today = date(2026, 8, 22)

    def new(self, **kw):
        return CardState(**kw)

    def test_new_card_good(self):
        s = self.new().with_review("good", self.today)
        self.assertEqual(s.repetitions, 1)
        self.assertEqual(s.interval_days, 1)
        self.assertEqual(s.due_date, self.today)
        self.assertEqual(s.ease_factor, 2.5)

    def test_new_card_easy(self):
        s = self.new().with_review("easy", self.today)
        self.assertEqual(s.repetitions, 1)
        self.assertEqual(s.interval_days, 2)
        self.assertEqual(s.ease_factor, 2.65)

    def test_new_card_hard(self):
        s = self.new().with_review("hard", self.today)
        self.assertEqual(s.repetitions, 1)
        self.assertEqual(s.interval_days, 1)
        self.assertEqual(s.ease_factor, 2.35)

    def test_new_card_again_stays_at_zero(self):
        s = self.new().with_review("again", self.today)
        self.assertEqual(s.repetitions, 0)
        self.assertEqual(s.interval_days, 0)
        self.assertEqual(s.due_date, self.today)
        self.assertEqual(s.ease_factor, 2.3)

    def test_reviewed_card_good_multiplies_interval(self):
        # repetitions 2, interval 2, ease 2.5 -> interval = round(2 * 2.5) = 5
        s = self.new(repetitions=2, interval_days=2).with_review("good", self.today)
        self.assertEqual(s.repetitions, 3)
        self.assertEqual(s.interval_days, 5)

    def test_reviewed_card_always_grows_at_least_one_day(self):
        s = self.new(repetitions=1, interval_days=1, ease_factor=1.3)
        s = s.with_review("hard", self.today)
        self.assertEqual(s.interval_days, 2)

    def test_easy_bonus(self):
        s = self.new(repetitions=2, interval_days=2)
        good = s.with_review("good", self.today)
        easy = self.new(repetitions=2, interval_days=2).with_review("easy", self.today)
        self.assertGreater(easy.interval_days, good.interval_days)

    def test_again_resets_to_learning(self):
        s = self.new(repetitions=3, interval_days=30, ease_factor=2.5)
        s = s.with_review("again", self.today)
        self.assertEqual(s.repetitions, 0)
        self.assertEqual(s.interval_days, 0)
        self.assertEqual(s.ease_factor, 2.3)

    def test_ease_clamped_at_minimum(self):
        s = self.new(repetitions=0, ease_factor=1.3).with_review("again", self.today)
        self.assertEqual(s.ease_factor, 1.3)

    def test_invalid_grade_raises(self):
        with self.assertRaises(ValueError):
            self.new().with_review("nope", self.today)


class TestStatus(unittest.TestCase):
    def test_suspended_wins(self):
        s = CardState(repetitions=5, interval_days=30)
        self.assertEqual(s.status(suspended=True), "suspended")

    def test_learning(self):
        self.assertEqual(CardState(repetitions=0).status(), "learning")
        self.assertEqual(CardState(repetitions=2).status(), "learning")

    def test_reviewing(self):
        self.assertEqual(CardState(repetitions=3, interval_days=5).status(), "reviewing")
        self.assertEqual(CardState(repetitions=9, interval_days=20).status(), "reviewing")

    def test_mature(self):
        self.assertEqual(CardState(repetitions=3, interval_days=21).status(), "mature")
        self.assertEqual(CardState(repetitions=5, interval_days=45).status(), "mature")


if __name__ == "__main__":
    unittest.main()
