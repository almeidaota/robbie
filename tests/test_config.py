import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from robbie.config import ConfigError, load_config, write_config


class TestConfig(unittest.TestCase):
    def tearDown(self):
        for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
            self._clear(key)

    def _clear(self, key):
        import os

        if key in os.environ:
            del os.environ[key]

    def test_missing_key_raises(self):
        with TemporaryDirectory() as tmp, patch(
            "robbie.config.ENV_FILE", Path(tmp) / ".env"
        ):
            (Path(tmp) / ".env").write_text("LLM_BASE_URL=https://example.com\n")
            with self.assertRaises(ConfigError):
                load_config()

    def test_loads_from_env(self):
        with patch.dict(
            "os.environ",
            {
                "LLM_API_KEY": "sk-test",
                "LLM_BASE_URL": "https://example.com",
                "LLM_MODEL": "m1",
            },
        ):
            config = load_config()
            self.assertEqual(config.api_key, "sk-test")
            self.assertEqual(config.base_url, "https://example.com")
            self.assertEqual(config.model, "m1")

    def test_defaults_applied(self):
        with patch.dict("os.environ", {"LLM_API_KEY": "sk-test"}):
            config = load_config()
            self.assertEqual(config.model, "deepseek-v4-flash")
            self.assertEqual(config.base_url, "https://api.deepseek.com")

    def test_env_overrides_dotenv(self):
        with TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("LLM_API_KEY=from-file\nLLM_MODEL=m-file\n")
            with patch.dict(
                "os.environ",
                {"LLM_API_KEY": "from-env", "LLM_BASE_URL": "https://env.example.com"},
            ), patch("robbie.config.ENV_FILE", env):
                config = load_config()
                self.assertEqual(config.api_key, "from-env")
                self.assertEqual(config.base_url, "https://env.example.com")
                self.assertEqual(config.model, "m-file")

    def test_write_config_round_trip(self):
        with TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            write_config("sk-secret", "https://example.com", "m1", env)
            with patch("robbie.config.ENV_FILE", env):
                config = load_config()
            self.assertEqual(config.api_key, "sk-secret")
            self.assertEqual(config.base_url, "https://example.com")
            self.assertEqual(config.model, "m1")

    def test_write_config_updates_existing_key(self):
        with TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("LLM_API_KEY=old\nPOSTGRES_USER=robbie\n")
            write_config("new-key", "https://example.com", "m2", env)
            content = env.read_text(encoding="utf-8")
            self.assertIn("LLM_API_KEY=new-key", content)
            self.assertIn("POSTGRES_USER=robbie", content)

    def test_write_config_chmod_600(self):
        import os

        with TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            write_config("sk", "https://example.com", "m", env)
            self.assertEqual(os.stat(env).st_mode & 0o777, 0o600)

    def test_write_config_skips_chmod_on_windows(self):
        import os

        with TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            with patch("robbie.config.os.name", "nt"):
                write_config("sk", "https://example.com", "m", env)
            self.assertTrue(env.exists())
            self.assertIn("LLM_API_KEY=sk", env.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
