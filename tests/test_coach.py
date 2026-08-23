import unittest

from robbie.coach import _extract_json
from robbie.parser import SchemaError


class TestExtractJson(unittest.TestCase):
    def test_raw_object(self):
        data = _extract_json('{"session_id": "x", "date": "2026-08-21"}')
        self.assertEqual(data["session_id"], "x")

    def test_fenced_object(self):
        data = _extract_json(
            'here you go:\n```json\n{"session_id": "x", "date": "2026-08-21"}\n```\nhope that works'
        )
        self.assertEqual(data["session_id"], "x")

    def test_surrounded_by_chatter(self):
        data = _extract_json(
            'Sure! The session record is {"session_id": "x", "date": "2026-08-21"} — let me know if you need changes.'
        )
        self.assertEqual(data["date"], "2026-08-21")

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            _extract_json("no json here at all, sorry")


class FakeLLM:
    """Scripted LLM for tests: returns replies from a list, no network."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, json_mode=False):
        self.calls.append(messages)
        return self.replies.pop(0)


GOOD_JSON = (
    '{"schema_version": 1, "session_id": "2026-08-21-99", "date": "2026-08-21", '
    '"topics": ["testing"], "notes": "n", "errors": [{"rule_id": "2", "type": "transfer", '
    '"quote": "q", "fix": "f", "self_caught": false}], "vocab_gaps": []}'
)

BAD_JSON = '{"schema_version": 1, "session_id": "2026-08-21-99", "date": "2026-08-21", "errors": [{"rule_id": "2", "type": "wrong-type", "quote": "q", "fix": "f"}]}'


class TestModeSwitching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from robbie.db import RobbieDB

        cls.db = RobbieDB(db_name="robbie_test")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_mode_defaults_to_casual(self):
        from robbie.coach import Coach

        coach = Coach(FakeLLM([]), self.db)
        self.assertEqual(coach.mode, "casual")

    def test_set_mode_and_unknown_mode_raises(self):
        from robbie.coach import Coach

        coach = Coach(FakeLLM([]), self.db, mode="formal")
        self.assertEqual(coach.mode, "formal")
        coach.set_mode("interview")
        self.assertEqual(coach.mode, "interview")
        with self.assertRaises(ValueError):
            coach.set_mode("nope")

    def test_system_prompt_includes_active_mode(self):
        from robbie.coach import Coach

        coach = Coach(FakeLLM([]), self.db)
        coach.set_mode("formal")
        prompt = coach.system_prompt()
        self.assertIn("## Active mode: formal", prompt)
        self.assertIn("Mode: formal", prompt)


class TestWrapUp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from robbie.db import RobbieDB

        cls.db = RobbieDB(db_name="robbie_test")
        cls.db.db.drop_collection("sessions")
        cls.db.db.drop_collection("errors")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_valid_json_accepted_first_try(self):
        from robbie.coach import Coach

        llm = FakeLLM([GOOD_JSON])
        coach = Coach(llm, self.db)
        data = coach.wrap_up([], "2026-08-21-99", "2026-08-21")
        self.assertEqual(data["session_id"], "2026-08-21-99")
        self.assertEqual(len(llm.calls), 1)

    def test_invalid_json_retries_then_succeeds(self):
        from robbie.coach import Coach

        llm = FakeLLM([BAD_JSON, GOOD_JSON])
        coach = Coach(llm, self.db)
        data = coach.wrap_up([], "2026-08-21-99", "2026-08-21")
        self.assertEqual(data["topics"], ["testing"])
        self.assertEqual(len(llm.calls), 2)
        # the retry message fed the validation error back
        self.assertIn("failed validation", llm.calls[1][-1]["content"])

    def test_gives_up_after_max_retries(self):
        from robbie.coach import Coach, CoachError

        llm = FakeLLM([BAD_JSON] * 4)
        coach = Coach(llm, self.db)
        with self.assertRaises(CoachError):
            coach.wrap_up([], "2026-08-21-99", "2026-08-21")
        self.assertEqual(len(llm.calls), 3)


if __name__ == "__main__":
    unittest.main()
