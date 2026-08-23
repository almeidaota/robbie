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

BRAIN_DIR = Path("robbie_brain")
AGENTS_FILE = BRAIN_DIR / "AGENTS.md"
MODE_AGENTS_DIR = BRAIN_DIR / "agents"
PROFILE_FILE = BRAIN_DIR / "profile.md"
RULES_FILE = BRAIN_DIR / "common_mistakes.md"
SESSION_LOG_FILE = BRAIN_DIR / "session_log.md"

MAX_RETRIES = 3

WRAP_UP_PROMPT = """\
The session is over. Write the session record as a single JSON object, no
other text, no markdown fences. Follow this schema exactly:

{
  "schema_version": 1,
  "session_id": "{session_id}",
  "date": "{date}",
  "topics": ["short topic", "..."],
  "notes": "one or two sentences about the session",
  "errors": [
    {{
      "rule_id": "<existing rule id, e.g. 2 or 11 — only create a NEW id if no existing rule fits>",
      "type": "grammar|transfer|typo|style",
      "quote": "what I actually wrote",
      "fix": "the corrected version",
      "self_caught": false
    }}
  ],
  "vocab_gaps": [
    {{"l1_word": "palavra", "target_word": "word", "context": "I need to (palavra?) that line"}}
  ]
}

Rules:
- ONLY include errors that actually happened in this session.
- type: grammar = wrong structure; transfer = Portuguese interference;
  typo = spelling/slip; style = valid but unnatural.
- self_caught: true only if I corrected myself mid-conversation.
- If a new error pattern showed up, give it a new short rule_id like
  "double-aux" and add a title in notes.
- For every vocab_gap, context MUST be the full sentence I actually typed,
  with the L1 word in parentheses where I flagged it. Never just "(word)"
  on its own — the sentence is what makes the gap learnable.
"""


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

        rules = self._rules_with_counts()
        if rules:
            parts.append("## Active rules with lifetime counts\n" + rules)

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

    def _rules_with_counts(self) -> str:
        counts = self._db.counts_by_rule()
        if not counts:
            return ""
        lines = []
        for doc in self._db.rules.find({"section": "active"}):
            rid = doc["rule_id"]
            if rid not in counts:
                continue
            lines.append(
                f"- [{rid}] {doc['title']} — {counts[rid]}x: "
                f"{doc['wrong'][:60]} → {doc['right'][:60]}"
            )
        return "\n".join(lines)

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
            WRAP_UP_PROMPT.replace("{session_id}", session_id)
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


def append_session_log(entry: str) -> None:
    """Append a wrap-up entry to robbie_brain/session_log.md."""
    SESSION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SESSION_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write("\n" + entry.rstrip() + "\n")


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
