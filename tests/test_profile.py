import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robbie.profile import QUESTIONS, _write_profile, apply_updates, ensure_profile


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


class TestApplyUpdates(unittest.TestCase):
    def _profile(self, tmp, extra: dict | None = None) -> Path:
        path = Path(tmp) / "profile.md"
        values = {label: "old" for label, _ in QUESTIONS}
        if extra:
            values.update(extra)
        _write_profile(path, values)
        return path

    def test_applies_matching_editable_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._profile(tmp)
            applied = apply_updates(
                path,
                [
                    ("Interests & life context", "started BJJ"),
                    ("Level", "advanced"),
                ],
            )
            self.assertEqual(
                set(applied), {"Interests & life context", "Level"}
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("- **Interests & life context:** started BJJ", text)
            self.assertIn("- **Level:** advanced", text)

    def test_ignores_fixed_fields_and_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._profile(tmp)
            applied = apply_updates(
                path,
                [
                    ("Native language", "English"),
                    ("Target language", "Portuguese"),
                    ("Nope", "whatever"),
                ],
            )
            self.assertEqual(applied, [])
            text = path.read_text(encoding="utf-8")
            self.assertIn("- **Native language:** Portuguese", text)
            self.assertIn("- **Target language:** English", text)

    def test_skips_unchanged_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._profile(tmp)
            applied = apply_updates(path, [("Level", "old")])
            self.assertEqual(applied, [])
            self.assertIn("- **Level:** old", path.read_text(encoding="utf-8"))

    def test_no_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.md"
            self.assertEqual(apply_updates(path, [("Level", "x")]), [])


if __name__ == "__main__":
    unittest.main()
