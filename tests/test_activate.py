import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from robbie.activate import (
    _connect_db,
    _count_words,
    _has_wrap_marker,
    _strip_wrap_marker,
    next_session_id,
)
from robbie.db import DBError


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


class TestConnectDb(unittest.TestCase):
    def test_connects_without_compose_when_db_is_up(self):
        with patch("robbie.activate.RobbieDB") as mock_db:
            self.assertIsNotNone(_connect_db())
        mock_db.assert_called_once()

    def test_starts_compose_and_retries_when_db_is_down(self):
        db_mock = unittest.mock.MagicMock()
        attempts = iter([DBError("down"), db_mock])
        with (
            patch("robbie.activate.RobbieDB", side_effect=attempts) as mock_db,
            patch("robbie.activate._compose_up", return_value=True) as compose,
        ):
            self.assertIs(_connect_db(max_retries=1), db_mock)
        compose.assert_called_once_with()
        self.assertEqual(mock_db.call_count, 2)

    def test_returns_none_when_compose_fails(self):
        with (
            patch("robbie.activate.RobbieDB", side_effect=DBError("down")),
            patch("robbie.activate._compose_up", return_value=False) as compose,
            patch("robbie.activate.console") as console,
        ):
            self.assertIsNone(_connect_db())
        compose.assert_called_once_with()
        console.print.assert_called()

    def test_returns_none_when_db_never_comes_up(self):
        with (
            patch("robbie.activate.RobbieDB", side_effect=DBError("down")),
            patch("robbie.activate._compose_up", return_value=True),
            patch("robbie.activate.time.sleep") as sleep,
            patch("robbie.activate.console") as console,
        ):
            self.assertIsNone(_connect_db(max_retries=2, delay=1.0))
        self.assertEqual(sleep.call_count, 1)
        console.print.assert_called()


if __name__ == "__main__":
    unittest.main()
