"""Robbie config: LLM credentials and settings.

Resolution order (later wins):
  1. defaults below
  2. ~/.config/robbie/config.toml (written by `robbie setup`)
  3. env vars: LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

The config file holds your API key — it's in your home dir, never in the repo.
"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "robbie"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

SYSTEM_PROMPT_EXTRA = ""


@dataclass
class Config:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL


class ConfigError(RuntimeError):
    """Raised when the config can't be found or parsed."""


def load_config(path: Path | None = None) -> Config:
    config_file = path or CONFIG_FILE
    file_data: dict = {}
    if config_file.exists():
        try:
            with config_file.open("rb") as f:
                file_data = tomllib.load(f)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            raise ConfigError(f"cannot read {config_file}: {exc}") from exc

    llm = file_data.get("llm", {})
    api_key = os.environ.get("LLM_API_KEY") or llm.get("api_key", "")
    base_url = os.environ.get("LLM_BASE_URL") or llm.get("base_url", DEFAULT_BASE_URL)
    model = os.environ.get("LLM_MODEL") or llm.get("model", DEFAULT_MODEL)

    if not api_key:
        raise ConfigError(
            "no LLM API key found — run `robbie setup` or set LLM_API_KEY"
        )
    return Config(api_key=api_key, base_url=base_url, model=model)


def write_config(api_key: str, base_url: str, model: str, path: Path | None = None) -> Path:
    """Write the config (chmod 600 — it holds a secret)."""
    target = path or CONFIG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f'[llm]\napi_key = {_toml_str(api_key)}\n'
        f"base_url = {_toml_str(base_url)}\n"
        f"model = {_toml_str(model)}\n"
    )
    target.write_text(content, encoding="utf-8")
    target.chmod(0o600)
    return target


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
