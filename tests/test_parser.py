import unittest
from pathlib import Path

from robbie.parser import (
    SchemaError,
    parse_session,
    parse_session_file,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.json"


class TestParseSession(unittest.TestCase):
    def test_parses_fixture(self):
        session = parse_session_file(FIXTURE)
        self.assertEqual(session.session_id, "2026-08-21-01")
        self.assertEqual(session.date, "2026-08-21")
        self.assertEqual(session.schema_version, 1)
        self.assertEqual(session.language, "en")
        self.assertEqual(session.topics, ["schema design", "parser"])
        self.assertEqual(len(session.errors), 8)
        self.assertEqual(len(session.vocab_gaps), 1)
        self.assertEqual(session.word_count, 200)

    def test_bad_word_count(self):
        with self.assertRaises(SchemaError):
            parse_session({
                "schema_version": 1,
                "session_id": "x",
                "date": "d",
                "word_count": -1,
            })
        with self.assertRaises(SchemaError):
            parse_session({
                "schema_version": 1,
                "session_id": "x",
                "date": "d",
                "word_count": "many",
            })

    def test_defaults(self):
        session = parse_session({
            "schema_version": 1,
            "session_id": "x",
            "date": "2026-08-21",
        })
        self.assertEqual(session.language, "en")
        self.assertEqual(session.mode, "casual")
        self.assertEqual(session.errors, [])
        self.assertEqual(session.vocab_gaps, [])
        self.assertEqual(session.notes, "")
        self.assertEqual(session.word_count, 0)

    def test_mode_field(self):
        session = parse_session({
            "schema_version": 1,
            "session_id": "x",
            "date": "2026-08-21",
            "mode": "formal",
        })
        self.assertEqual(session.mode, "formal")

    def test_unknown_mode(self):
        with self.assertRaises(SchemaError):
            parse_session({
                "schema_version": 1,
                "session_id": "x",
                "date": "d",
                "mode": "shouting",
            })

    def test_error_fields(self):
        session = parse_session_file(FIXTURE)
        first = session.errors[0]
        self.assertEqual(first.type, "transfer")
        self.assertEqual(first.quote, "store the file into a database")
        self.assertEqual(first.fix, "store the file in a database")
        self.assertFalse(first.self_caught)

    def test_vocab_gap_fields(self):
        session = parse_session_file(FIXTURE)
        gap = session.vocab_gaps[0]
        self.assertEqual(gap.l1_word, "substituir")
        self.assertEqual(gap.target_word, "replace")
        self.assertEqual(gap.context, "I need to (substituir?) that line")

    def test_defaults(self):
        session = parse_session({
            "schema_version": 1,
            "session_id": "x",
            "date": "2026-08-21",
        })
        self.assertEqual(session.language, "en")
        self.assertEqual(session.errors, [])
        self.assertEqual(session.vocab_gaps, [])
        self.assertEqual(session.notes, "")

    def test_missing_session_id(self):
        with self.assertRaises(SchemaError):
            parse_session({"schema_version": 1, "date": "2026-08-21"})

    def test_missing_date(self):
        with self.assertRaises(SchemaError):
            parse_session({"schema_version": 1, "session_id": "x"})

    def test_bad_schema_version_type(self):
        with self.assertRaises(SchemaError):
            parse_session({"schema_version": "1", "session_id": "x", "date": "d"})

    def test_unsupported_schema_version(self):
        with self.assertRaises(SchemaError):
            parse_session({"schema_version": 2, "session_id": "x", "date": "d"})

    def test_unknown_type(self):
        with self.assertRaises(SchemaError):
            parse_session({
                "schema_version": 1,
                "session_id": "x",
                "date": "d",
                "errors": [{"type": "nah", "quote": "q", "fix": "f"}],
            })

    def test_non_boolean_self_caught(self):
        with self.assertRaises(SchemaError):
            parse_session({
                "schema_version": 1,
                "session_id": "x",
                "date": "d",
                "errors": [{"type": "typo", "quote": "q", "fix": "f", "self_caught": "yes"}],
            })

    def test_error_missing_fix(self):
        with self.assertRaises(SchemaError):
            parse_session({
                "schema_version": 1,
                "session_id": "x",
                "date": "d",
                "errors": [{"type": "typo", "quote": "q"}],
            })

    def test_missing_file(self):
        with self.assertRaises(SchemaError):
            parse_session_file(Path("/nonexistent/session.json"))

    def test_invalid_json(self):
        bad = Path(__file__).parent / "fixtures" / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        try:
            with self.assertRaises(SchemaError):
                parse_session_file(bad)
        finally:
            bad.unlink()

    def test_non_object_root(self):
        with self.assertRaises(SchemaError):
            parse_session([1, 2, 3])  # type: ignore[arg-type]


class TestRating(unittest.TestCase):
    def setUp(self):
        self.session = parse_session_file(FIXTURE)

    def test_fixture_rating(self):
        # 5*0.6 (transfer) + 1*1.0 (grammar) + 0.6*0.5 (transfer, self-caught) + 1*0.3 (typo)
        # = 3.0 + 1.0 + 0.3 + 0.3 = 4.6  ->  10 - 4.6 = 5.4
        self.assertEqual(self.session.rating(), 5.4)

    def test_errors_per_100_words(self):
        # fixture: 8 errors / 200 words * 100 = 4.0
        self.assertEqual(self.session.errors_per_100_words(), 4.0)

    def test_errors_per_100_words_unknown(self):
        session = parse_session({
            "schema_version": 1,
            "session_id": "x",
            "date": "2026-08-21",
            "errors": [{"type": "typo", "quote": "q", "fix": "f"}],
        })
        self.assertIsNone(session.errors_per_100_words())

    def test_clean_session_is_10(self):
        session = parse_session({
            "schema_version": 1,
            "session_id": "clean",
            "date": "2026-08-21",
        })
        self.assertEqual(session.rating(), 10.0)

    def test_rating_clamps_at_zero(self):
        session = parse_session({
            "schema_version": 1,
            "session_id": "rough",
            "date": "2026-08-21",
            "errors": [{"type": "grammar", "quote": "q", "fix": "f"}] * 20,
        })
        self.assertEqual(session.rating(), 0.0)

    def test_style_is_zero_weight(self):
        session = parse_session({
            "schema_version": 1,
            "session_id": "x",
            "date": "d",
            "errors": [{"type": "style", "quote": "q", "fix": "f"}],
        })
        self.assertEqual(session.rating(), 10.0)

    def test_self_caught_halves_penalty(self):
        base = parse_session({
            "schema_version": 1,
            "session_id": "x",
            "date": "d",
            "errors": [{"type": "grammar", "quote": "q", "fix": "f"}],
        })
        self.assertEqual(base.rating(), 9.0)
        self_caught = parse_session({
            "schema_version": 1,
            "session_id": "x",
            "date": "d",
            "errors": [{"type": "grammar", "quote": "q", "fix": "f", "self_caught": True}],
        })
        self.assertEqual(self_caught.rating(), 9.5)


class TestCounters(unittest.TestCase):
    def setUp(self):
        self.session = parse_session_file(FIXTURE)

    def test_counts_by_type(self):
        self.assertEqual(self.session.counts_by_type(), {"transfer": 6, "grammar": 1, "typo": 1})


if __name__ == "__main__":
    unittest.main()
