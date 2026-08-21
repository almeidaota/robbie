import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from robbie.config import Config, ConfigError, load_config, write_config


class TestConfig(unittest.TestCase):
    def test_missing_key_raises(self):
        with TemporaryDirectory() as tmp:
            empty = Path(tmp) / "config.toml"
            empty.write_text("", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(empty)

    def test_loads_from_file(self):
        with TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(
                '[llm]\napi_key = "sk-test"\nbase_url = "https://example.com"\nmodel = "m1"\n',
                encoding="utf-8",
            )
            config = load_config(cfg)
            self.assertEqual(config.api_key, "sk-test")
            self.assertEqual(config.base_url, "https://example.com")
            self.assertEqual(config.model, "m1")

    def test_defaults_applied(self):
        with TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text('[llm]\napi_key = "sk-test"\n', encoding="utf-8")
            config = load_config(cfg)
            self.assertEqual(config.model, "deepseek-chat")
            self.assertTrue(config.base_url.startswith("https://"))

    def test_write_config_round_trip(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            written = write_config("sk-secret", "https://example.com", "m1", path)
            config = load_config(written)
            self.assertEqual(config.api_key, "sk-secret")
            self.assertEqual(config.base_url, "https://example.com")
            self.assertEqual(config.model, "m1")

    def test_toml_escaping(self):
        from robbie.config import _toml_str

        self.assertEqual(_toml_str('say "hi"'), '"say \\"hi\\""')
        self.assertEqual(_toml_str("a\\b"), '"a\\\\b"')


if __name__ == "__main__":
    unittest.main()
