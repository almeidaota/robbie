import contextlib
import io
import unittest
from unittest.mock import patch

from robbie.cli import MODELS_BY_PROVIDER, _pick_model


def pick(*inputs):
    out = io.StringIO()
    with patch("builtins.input", side_effect=list(inputs)), contextlib.redirect_stdout(out):
        return _pick_model("https://api.deepseek.com")


class TestPickModel(unittest.TestCase):
    def test_deepseek_options(self):
        self.assertEqual(MODELS_BY_PROVIDER["deepseek"], ["deepseek-chat", "deepseek-reasoner"])

    def test_defaults_to_first(self):
        self.assertEqual(pick(""), "deepseek-chat")

    def test_selects_by_number(self):
        self.assertEqual(pick("2"), "deepseek-reasoner")

    def test_custom_option(self):
        self.assertEqual(pick("3", "my-model"), "my-model")

    def test_invalid_then_valid(self):
        self.assertEqual(pick("9", ""), "deepseek-chat")

    def test_unknown_provider_falls_back_to_input(self):
        out = io.StringIO()
        with patch("builtins.input", side_effect=["custom-model"]), contextlib.redirect_stdout(out):
            result = _pick_model("https://unknown.example.com")
        self.assertEqual(result, "custom-model")


if __name__ == "__main__":
    unittest.main()
