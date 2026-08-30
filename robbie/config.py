"""Robbie config: all credentials live in the repo-root .env file.

Resolution order (later wins):
  1. defaults below
  2. values in .env (loaded via python-dotenv, with no override)
  3. already-set environment variables always win

The .env holds the API key — it's gitignored, never in the repo.
`robbie setup` writes/updates it interactively (chmod 600).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT_DIR / ".env"

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

SYSTEM_PROMPT_EXTRA = ""


@dataclass
class Config:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL


class ConfigError(RuntimeError):
    """Raised when the config can't be found or parsed."""


def load_config() -> Config:
    """Read credentials from .env + environment (env vars win)."""
    load_dotenv(ENV_FILE, override=False)
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL)
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    if not api_key:
        raise ConfigError(
            "no LLM API key found — run `robbie setup` or set LLM_API_KEY in .env"
        )
    return Config(api_key=api_key, base_url=base_url, model=model)


def write_config(
    api_key: str,
    base_url: str,
    model: str,
    path: Path | None = None,
) -> Path:
    """Write or update the .env with the LLM settings (chmod 600)."""
    target = path or ENV_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    load_dotenv(target, override=False)
    updates = {
        "LLM_API_KEY": api_key,
        "LLM_BASE_URL": base_url,
        "LLM_MODEL": model,
    }

    lines = _read_env_lines(target)
    keys = set(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in keys:
            out.append(f"{key}={updates[key]}")
            keys.discard(key)
        else:
            out.append(line)
    for key in keys:
        out.append(f"{key}={updates[key]}")

    target.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    _restrict_permissions(target)
    return target


def _restrict_permissions(path: Path) -> None:
    """Restrict .env permissions where the OS supports it (chmod is Unix-only)."""
    if os.name == "nt":
        return
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _read_env_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
