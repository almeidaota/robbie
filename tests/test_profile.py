import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robbie.profile import QUESTIONS, _write_profile, ensure_profile


class TestEnsureProfile(unittest.TestCase):
    def test_creates_profile_from_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.md"
            answers = ["Ana", "advanced", "work", "music", "", ""]
            created = ensure_profile(path, answers=list(answers))
            self.assertTrue(created)
            text = path.read_text(encoding="utf-8")
            self.assertIn("# Learner Profile", text)
            self.assertIn("- **Name / nickname:** Ana", text)
            self.assertIn("- **Level:** advanced", text)
            self.assertIn("- **Native language:** Portuguese", text)
            self.assertIn("- **Target language:** English", text)
            self.assertIn("- **Things the coach should never forget:**", text)

    def test_skips_when_profile_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.md"
            path.write_text("already here", encoding="utf-8")
            created = ensure_profile(path, answers=["x"])
            self.assertFalse(created)
            self.assertEqual(path.read_text(encoding="utf-8"), "already here")

    def test_empty_answers_use_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.md"
            created = ensure_profile(path, answers=[""] * len(QUESTIONS))
            self.assertTrue(created)
            text = path.read_text(encoding="utf-8")
            self.assertIn("- **Level:** upper-intermediate", text)

    def test_interactive_with_eof_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.md"
            with patch("robbie.profile.console") as console:
                console.input.side_effect = EOFError
                created = ensure_profile(path)
            self.assertTrue(created)
            text = path.read_text(encoding="utf-8")
            self.assertIn("- **Native language:** Portuguese", text)


class TestWriteProfile(unittest.TestCase):
    def test_renders_all_question_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.md"
            values = {label: f"v-{label}" for label, _ in QUESTIONS}
            _write_profile(path, values)
            text = path.read_text(encoding="utf-8")
            for label, _ in QUESTIONS:
                self.assertIn(f"- **{label}:** v-{label}", text)


if __name__ == "__main__":
    unittest.main()
