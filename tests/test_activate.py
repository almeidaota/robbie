import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from robbie.activate import (
    _count_words,
    _has_wrap_marker,
    _strip_wrap_marker,
    next_session_id,
)


class TestActivateHelpers(unittest.TestCase):
    def test_count_words(self):
        self.assertEqual(_count_words("hello there friend"), 3)
        self.assertEqual(_count_words("  spaced   out  "), 2)
        self.assertEqual(_count_words(""), 0)

    def test_wrap_marker_detection(self):
        self.assertTrue(_has_wrap_marker("ok, done\n<wrap_up>"))
        self.assertFalse(_has_wrap_marker("ok, done"))
        self.assertEqual(_strip_wrap_marker("bye\n<wrap_up>"), "bye\n")

    def test_next_session_id_counts_existing(self):
        with TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            (sessions / "2026-08-21-01.json").write_text("{}")
            (sessions / "2026-08-21-02.json").write_text("{}")
            with patch("robbie.activate.SESSIONS_DIR", sessions):
                with patch("robbie.activate.date") as mock_date:
                    mock_date.today.return_value.isoformat.return_value = "2026-08-21"
                    self.assertEqual(next_session_id(), "2026-08-21-03")

    def test_next_session_id_first_of_day(self):
        with TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            with patch("robbie.activate.SESSIONS_DIR", sessions):
                with patch("robbie.activate.date") as mock_date:
                    mock_date.today.return_value.isoformat.return_value = "2026-08-22"
                    self.assertEqual(next_session_id(), "2026-08-22-01")


if __name__ == "__main__":
    unittest.main()
