import unittest
from unittest.mock import MagicMock, patch

from robbie.activate import (
    _connect_db,
    _count_words,
    _has_wrap_marker,
    _offer_profile_updates,
    _show_session_facts,
    _strip_wrap_marker,
    next_session_id,
)
from robbie.db import DBError
from robbie.parser import ErrorEntry, ProfileUpdate, Session, VocabGap


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
        db = MagicMock()
        db.session_ids_on.return_value = ["2026-08-21-01", "2026-08-21-02"]
        with patch("robbie.activate.date") as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2026-08-21"
            self.assertEqual(next_session_id(db), "2026-08-21-03")
        db.session_ids_on.assert_called_once_with("2026-08-21")

    def test_next_session_id_ignores_ids_from_other_days(self):
        db = MagicMock()
        db.session_ids_on.return_value = ["2026-08-20-01", "2026-08-21-02"]
        with patch("robbie.activate.date") as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2026-08-21"
            self.assertEqual(next_session_id(db), "2026-08-21-03")

    def test_next_session_id_first_of_day(self):
        db = MagicMock()
        db.session_ids_on.return_value = []
        with patch("robbie.activate.date") as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2026-08-22"
            self.assertEqual(next_session_id(db), "2026-08-22-01")


class TestShowSessionFacts(unittest.TestCase):
    def test_prints_errors_and_gaps(self):
        from unittest.mock import patch

        session = Session(
            session_id="x",
            date="2026-08-22",
            errors=[ErrorEntry("transfer", "wasnt", "wasn't")],
            vocab_gaps=[VocabGap("mesmo", "actually", "(mesmo)")],
        )
        with patch("robbie.activate.console") as console:
            _show_session_facts(session)
        texts = " ".join(str(c.args) for c in console.print.call_args_list)
        self.assertIn("wasn't", texts)
        self.assertIn("mesmo", texts)
        self.assertIn("actually", texts)

    def test_quiet_when_no_facts(self):
        from unittest.mock import patch

        session = Session(session_id="x", date="2026-08-22")
        with patch("robbie.activate.console") as console:
            _show_session_facts(session)
        console.print.assert_not_called()


class TestOfferProfileUpdates(unittest.TestCase):
    def test_applies_on_yes(self):
        import tempfile
        from unittest.mock import patch
        from pathlib import Path

        from robbie.profile import _write_profile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.md"
            _write_profile(path, {"Level": "intermediate"})
            updates = [ProfileUpdate(field="Level", value="advanced")]
            with (
                patch("robbie.activate.console") as console,
                patch("robbie.activate.PROFILE_FILE", path),
                patch("robbie.activate.console.input", return_value="y"),
            ):
                _offer_profile_updates(updates)
            self.assertIn("- **Level:** advanced", path.read_text(encoding="utf-8"))
            console.print.assert_called()

    def test_leaves_unchanged_on_no(self):
        import tempfile
        from unittest.mock import patch
        from pathlib import Path

        from robbie.profile import _write_profile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.md"
            _write_profile(path, {"Level": "intermediate"})
            updates = [ProfileUpdate(field="Level", value="advanced")]
            with (
                patch("robbie.activate.console") as console,
                patch("robbie.activate.PROFILE_FILE", path),
                patch("robbie.activate.console.input", return_value="n"),
            ):
                _offer_profile_updates(updates)
            self.assertIn("- **Level:** intermediate", path.read_text(encoding="utf-8"))


class TestConnectDb(unittest.TestCase):
    def test_connects(self):
        with patch("robbie.activate.RobbieDB") as mock_db:
            self.assertIsNotNone(_connect_db())
        mock_db.assert_called_once()

    def test_returns_none_when_open_fails(self):
        with (
            patch("robbie.activate.RobbieDB", side_effect=DBError("down")),
            patch("robbie.activate.console") as console,
        ):
            self.assertIsNone(_connect_db())
        console.print.assert_called()


if __name__ == "__main__":
    unittest.main()
