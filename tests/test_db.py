import unittest

from robbie.parser import ErrorEntry, Session, VocabGap
from robbie.db import DBError, RobbieDB


def make_session(session_id="2026-08-21-01", with_errors=True, mode="casual", date="2026-08-21"):
    return Session(
        session_id=session_id,
        date=date,
        mode=mode,
        topics=["schema design"],
        notes="test",
        word_count=150,
        errors=[
            ErrorEntry("transfer", "store the file into a database", "store the file in a database"),
            ErrorEntry("grammar", "a very good day", "a very good day", self_caught=True),
        ]
        if with_errors
        else [],
        vocab_gaps=[VocabGap("substituir", "replace", "I need to (substituir?) that line")],
    )


class TestRobbieDB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = RobbieDB(db_name="robbie_test")

    @classmethod
    def tearDownClass(cls):
        cls.store.close()

    def setUp(self):
        self.store.clear()

    def test_round_trip(self):
        self.store.upsert_session(make_session())
        got = self.store.get_session("2026-08-21-01")
        self.assertIsNotNone(got)
        self.assertEqual(got.rating(), 10.0 - (0.6 + 1.0 * 0.5))
        self.assertEqual(got.word_count, 150)
        self.assertEqual(got.vocab_gaps[0].l1_word, "substituir")

    def test_mode_round_trip(self):
        self.store.upsert_session(make_session(mode="formal"))
        got = self.store.get_session("2026-08-21-01")
        self.assertEqual(got.mode, "formal")
        row = self.store._conn.execute(
            "SELECT mode FROM sessions WHERE session_id = %s", ("2026-08-21-01",)
        ).fetchone()
        self.assertEqual(row["mode"], "formal")

    def test_upsert_replaces(self):
        self.store.upsert_session(make_session(with_errors=True))
        self.store.upsert_session(make_session(with_errors=False))
        got = self.store.get_session("2026-08-21-01")
        self.assertEqual(got.errors, [])
        rows = self.store._conn.execute(
            "SELECT * FROM errors WHERE session_id = %s", ("2026-08-21-01",)
        ).fetchall()
        self.assertEqual(rows, [])

    def test_rating_not_stored(self):
        self.store.upsert_session(make_session())
        row = self.store._conn.execute(
            "SELECT * FROM sessions WHERE session_id = %s", ("2026-08-21-01",)
        ).fetchone()
        self.assertNotIn("rating", row)

    def test_all_sessions_sorted(self):
        self.store.upsert_session(make_session("2026-08-20-01"))
        self.store.upsert_session(make_session("2026-08-21-01"))
        ids = [s.session_id for s in self.store.all_sessions()]
        self.assertEqual(ids, ["2026-08-20-01", "2026-08-21-01"])

    def test_counts_by_type(self):
        self.store.upsert_session(make_session())
        self.assertEqual(self.store.counts_by_type(), {"transfer": 1, "grammar": 1})

    def test_session_ids_on(self):
        self.store.upsert_session(make_session("2026-08-20-01", date="2026-08-20"))
        self.store.upsert_session(make_session("2026-08-21-01"))
        self.store.upsert_session(make_session("2026-08-21-02"))
        self.assertEqual(
            self.store.session_ids_on("2026-08-21"),
            ["2026-08-21-01", "2026-08-21-02"],
        )

    def test_unreachable_raises(self):
        with self.assertRaises(DBError):
            RobbieDB(dsn="postgresql://localhost:1/robbie")


class TestCards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = RobbieDB(db_name="robbie_test")

    @classmethod
    def tearDownClass(cls):
        cls.store.close()

    def setUp(self):
        self.store.clear()

    def gap_session(self, session_id="2026-08-21-01", date="2026-08-21"):
        return Session(
            session_id=session_id,
            date=date,
            vocab_gaps=[
                VocabGap("substituir", "replace", "I need to (substituir?) that line", date),
                VocabGap("atualize", "update", "please (atualize?) the docs", date),
            ],
        )

    def test_sync_creates_cards(self):
        n = self.store.sync_cards_from_session(self.gap_session())
        self.assertEqual(n, 2)
        card = self.store.get_card("substituir->replace")
        self.assertEqual(card["l1_word"], "substituir")
        self.assertEqual(card["target_word"], "replace")
        self.assertEqual(card["times_gapped"], 1)
        self.assertEqual(card["due_date"], "2026-08-21")
        self.assertEqual(card["repetitions"], 0)
        self.assertEqual(card["ease_factor"], 2.5)
        self.assertEqual(len(card["contexts"]), 1)

    def test_sync_appends_context_and_bumps(self):
        self.store.sync_cards_from_session(self.gap_session())
        second = Session(
            session_id="2026-08-22-01",
            date="2026-08-22",
            vocab_gaps=[VocabGap("substituir", "replace", "I need to (substituir?) that line", "2026-08-22")],
        )
        self.store.sync_cards_from_session(second)
        card = self.store.get_card("substituir->replace")
        self.assertEqual(card["times_gapped"], 2)
        self.assertEqual(len(card["contexts"]), 2)
        self.assertEqual(card["last_seen"], "2026-08-22")
        self.assertEqual(card["first_seen"], "2026-08-21")

    def test_sync_is_idempotent_per_session(self):
        s = self.gap_session()
        self.store.sync_cards_from_session(s)
        self.store.sync_cards_from_session(s)
        card = self.store.get_card("substituir->replace")
        self.assertEqual(card["times_gapped"], 1)
        self.assertEqual(len(card["contexts"]), 1)

    def test_sync_bumps_twice_for_two_contexts_in_one_session(self):
        s = Session(
            session_id="2026-08-21-01",
            date="2026-08-21",
            vocab_gaps=[
                VocabGap("substituir", "replace", "I need to (substituir?) that line", "2026-08-21"),
                VocabGap("substituir", "replace", "can you (substituir?) the name", "2026-08-21"),
            ],
        )
        self.store.sync_cards_from_session(s)
        card = self.store.get_card("substituir->replace")
        self.assertEqual(card["times_gapped"], 2)
        self.assertEqual(len(card["contexts"]), 2)

    def test_due_cards(self):
        self.store.sync_cards_from_session(self.gap_session())
        self.assertEqual(len(self.store.due_cards("2026-08-22")), 2)
        self.assertEqual(self.store.due_cards("2026-08-20"), [])

    def test_count_due_cards(self):
        self.store.sync_cards_from_session(self.gap_session())
        self.assertEqual(self.store.count_due_cards("2026-08-22"), 2)
        self.assertEqual(self.store.count_due_cards("2026-08-20"), 0)

    def test_review_advances_state(self):
        self.store.sync_cards_from_session(self.gap_session())
        card = self.store.review_card("substituir->replace", "good", "2026-08-22")
        self.assertEqual(card["repetitions"], 1)
        self.assertEqual(card["interval_days"], 1)
        self.assertEqual(card["due_date"], "2026-08-22")
        self.assertEqual(card["last_reviewed"], "2026-08-22")
        self.assertEqual(self.store.card_status(card), "learning")

        card = self.store.review_card("substituir->replace", "again", "2026-08-22")
        self.assertEqual(card["repetitions"], 0)
        self.assertEqual(card["interval_days"], 0)

    def test_review_unknown_card_raises(self):
        with self.assertRaises(KeyError):
            self.store.review_card("nope->never", "good", "2026-08-22")

    def test_suspended_cards_not_due(self):
        self.store.sync_cards_from_session(self.gap_session())
        self.store._conn.execute(
            "UPDATE cards SET suspended = TRUE WHERE slug = %s", ("substituir->replace",)
        )
        due = self.store.due_cards("2026-08-22")
        self.assertEqual([d["slug"] for d in due], ["atualize->update"])


if __name__ == "__main__":
    unittest.main()
