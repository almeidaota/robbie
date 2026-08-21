import unittest
from unittest.mock import patch

from robbie.parser import ErrorEntry, Session, VocabGap
from robbie.db import DBError, RobbieDB


def make_session(session_id="2026-08-21-01", with_errors=True):
    return Session(
        session_id=session_id,
        date="2026-08-21",
        topics=["schema design"],
        notes="test",
        word_count=150,
        errors=[
            ErrorEntry("2", "transfer", "store the file into a database", "store the file in a database"),
            ErrorEntry("6", "grammar", "a very good day", "a very good day", self_caught=True),
        ]
        if with_errors
        else [],
        vocab_gaps=[VocabGap("substituir", "replace", "I need to (substituir?) that line")],
    )


class TestRobbieDB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = RobbieDB()

    @classmethod
    def tearDownClass(cls):
        cls.store.close()

    def setUp(self):
        self.store.db.drop_collection("sessions")
        self.store.db.drop_collection("errors")

    def test_round_trip(self):
        self.store.upsert_session(make_session())
        got = self.store.get_session("2026-08-21-01")
        self.assertIsNotNone(got)
        self.assertEqual(got.rating(), 10.0 - (0.6 + 1.0 * 0.5))
        self.assertEqual(got.counts_by_rule(), {"2": 1, "6": 1})
        self.assertEqual(got.word_count, 150)
        self.assertEqual(got.vocab_gaps[0].l1_word, "substituir")

    def test_upsert_replaces(self):
        self.store.upsert_session(make_session(with_errors=True))
        self.store.upsert_session(make_session(with_errors=False))
        got = self.store.get_session("2026-08-21-01")
        self.assertEqual(got.errors, [])
        self.assertEqual(list(self.store.errors.find({"session_id": "2026-08-21-01"})), [])

    def test_rating_not_stored(self):
        self.store.upsert_session(make_session())
        doc = self.store.sessions.find_one({"_id": "2026-08-21-01"})
        self.assertNotIn("rating", doc)

    def test_all_sessions_sorted(self):
        self.store.upsert_session(make_session("2026-08-20-01"))
        self.store.upsert_session(make_session("2026-08-21-01"))
        ids = [s.session_id for s in self.store.all_sessions()]
        self.assertEqual(ids, ["2026-08-20-01", "2026-08-21-01"])

    def test_counts_by_type(self):
        self.store.upsert_session(make_session())
        self.assertEqual(self.store.counts_by_type(), {"transfer": 1, "grammar": 1})

    def test_unreachable_raises(self):
        with self.assertRaises(DBError):
            RobbieDB(uri="mongodb://localhost:1")

    def test_sync_rules_replaces_and_finds_orphans(self):
        self.store.sync_rules("robbie_brain/common_mistakes.md")
        n = self.store.rules.count_documents({})
        self.assertEqual(n, 23)
        r2 = self.store.rules.find_one({"_id": "2"})
        self.assertEqual(r2["times_repeated"], 10)

        self.store.upsert_session(make_session())
        orphans = self.store.orphan_rule_ids()
        self.assertIn("2", self.store.rules.distinct("rule_id"))
        self.assertNotIn("2", orphans)

        self.store.errors.insert_one({"session_id": "2026-08-21-01", "rule_id": "nope"})
        self.assertEqual(self.store.orphan_rule_ids(), ["nope"])


if __name__ == "__main__":
    unittest.main()
