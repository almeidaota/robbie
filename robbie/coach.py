"""The coach: deterministic context assembly + LLM calls.

Recognition of errors stays fuzzy (the LLM does it). Everything around it is
deterministic: what gets injected into the prompt is assembled by code, and
the wrap-up JSON must pass our schema before it's stored.
"""

import json
import re
from pathlib import Path

from .db import RobbieDB
from .parser import DEFAULT_MODE, MODES, SchemaError, parse_session

# Repo root, resolved from this file — robbie works no matter where it's run.
ROOT_DIR = Path(__file__).resolve().parents[1]
BRAIN_DIR = ROOT_DIR / "robbie_brain"
AGENTS_FILE = BRAIN_DIR / "AGENTS.md"
MODE_AGENTS_DIR = BRAIN_DIR / "agents"
PROFILE_FILE = BRAIN_DIR / "profile.md"
WRAP_UP_PROMPT_FILE = BRAIN_DIR / "wrap_up_prompt.md"

MAX_RETRIES = 3


class CoachError(RuntimeError):
    """Raised when the coach can't produce a valid wrap-up."""


class Coach:
    def __init__(self, llm, db: RobbieDB, mode: str = DEFAULT_MODE) -> None:
        self._llm = llm
        self._db = db
        self.set_mode(mode)

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}, expected one of {MODES}")
        self._mode = mode

    def system_prompt(self) -> str:
        """Assemble the system prompt deterministically, with the active mode."""
        parts = [_read_or("", AGENTS_FILE)]

        mode_prompt = _read_or("", MODE_AGENTS_DIR / f"{self._mode}.md")
        if mode_prompt:
            parts.append(f"## Active mode: {self._mode}\n" + mode_prompt)

        profile = _read_or("", PROFILE_FILE)
        if profile:
            parts.append("## Learner profile\n" + profile)

        recent = self._recent_sessions()
        if recent:
            parts.append("## Last sessions\n" + recent)

        parts.append(
            "You are talking to the learner in the terminal. Reply like a "
            "casual friend. When the learner indicates the session is over "
            "(for example \"let's wrap up\", \"I want to stop\", \"I'm done\", "
            "or /quit), end your reply with the marker <wrap_up> on its own "
            "line. The app reads that marker and starts the session wrap-up."
        )
        return "\n\n".join(parts)

    def _recent_sessions(self) -> str:
        sessions = list(self._db.all_sessions())[-2:]
        if not sessions:
            return ""
        lines = []
        for s in sessions:
            lines.append(
                f"- {s.date}: {', '.join(s.topics) if s.topics else '(no topics)'} "
                f"(rating {s.rating():.1f})"
            )
        return "\n".join(lines)

    def wrap_up(self, history: list[dict], session_id: str, date: str) -> dict:
        """Ask the coach for the session JSON; validate; retry on schema errors."""
        prompt = (
            _read_or("", WRAP_UP_PROMPT_FILE).replace("{session_id}", session_id)
            .replace("{date}", date)
        )
        messages = [{"role": "system", "content": self.system_prompt()}]
        messages += history
        messages.append({"role": "user", "content": prompt})

        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                reply = self._llm.chat(messages, json_mode=True)
                data = _extract_json(reply)
                parse_session(data)
                return data
            except (SchemaError, ValueError, json.JSONDecodeError) as exc:
                last_error = str(exc)
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"That session JSON failed validation: {last_error}. "
                            "Reply again with ONLY the corrected JSON object."
                        ),
                    }
                )
        raise CoachError(
            f"coach could not produce a valid session JSON after {MAX_RETRIES} "
            f"attempts. Last error: {last_error}"
        )


def _read_or(default: str, path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return default


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of an LLM reply (fenced or raw)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object found in reply: {text[:200]!r}")
    return json.loads(text[start : end + 1])
