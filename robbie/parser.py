"""Parse session files and compute deterministic ratings.

Recognition of errors stays fuzzy (human/AI decides). Everything here is
deterministic: given a session JSON, the same file always yields the same
rating, counts, and structure.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SUPPORTED_TYPES = ("grammar", "transfer", "typo", "style")

MODES = ("casual", "formal", "interview")
DEFAULT_MODE = "casual"

# Weights per error type. Deterministic, single source of truth.
# Adjust these and re-run on old files: every past session re-scores consistently.
WEIGHTS = {
    "grammar": 1.0,   # heavy
    "transfer": 0.6,  # medium (Portuguese/Italian interference)
    "typo": 0.3,      # light
    "style": 0.0,     # zero — never docks the rating
}

# A self-caught error docks half the weight: recognition deserves credit.
SELF_CAUGHT_FACTOR = 0.5

BASE_RATING = 10.0
MIN_RATING = 0.0
MAX_RATING = 10.0


class SchemaError(ValueError):
    """Raised when a session file doesn't match the schema."""


@dataclass
class ErrorEntry:
    rule_id: str
    type: str
    quote: str
    fix: str
    self_caught: bool = False

    def penalty(self) -> float:
        weight = WEIGHTS[self.type]
        if self.self_caught:
            weight *= SELF_CAUGHT_FACTOR
        return weight


@dataclass
class VocabGap:
    l1_word: str
    target_word: str
    context: str
    date: str = ""


@dataclass
class Session:
    session_id: str
    date: str
    schema_version: int = SCHEMA_VERSION
    language: str = "en"
    mode: str = DEFAULT_MODE
    topics: list[str] = field(default_factory=list)
    notes: str = ""
    word_count: int = 0
    errors: list[ErrorEntry] = field(default_factory=list)
    vocab_gaps: list[VocabGap] = field(default_factory=list)

    def rating(self) -> float:
        penalty = sum(e.penalty() for e in self.errors)
        rating = BASE_RATING - penalty
        return round(min(max(rating, MIN_RATING), MAX_RATING), 1)

    def errors_per_100_words(self) -> float | None:
        """Errors per 100 user-written words. None when word count is unknown."""
        if self.word_count <= 0:
            return None
        return round(len(self.errors) / self.word_count * 100, 2)

    def counts_by_rule(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.errors:
            counts[e.rule_id] = counts.get(e.rule_id, 0) + 1
        return counts

    def counts_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.errors:
            counts[e.type] = counts.get(e.type, 0) + 1
        return counts


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise SchemaError(f"missing required field: {key!r}")
    return data[key]


def parse_session_file(path: str | Path) -> Session:
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as exc:
        raise SchemaError(f"session file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SchemaError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SchemaError("session file must be a JSON object")
    return parse_session(data)


def parse_session(data: dict[str, Any]) -> Session:
    version = _require(data, "schema_version")
    if not isinstance(version, int):
        raise SchemaError("schema_version must be an integer")
    if version > SCHEMA_VERSION:
        raise SchemaError(
            f"unsupported schema_version {version} (this parser knows up to {SCHEMA_VERSION})"
        )

    errors = []
    for i, raw in enumerate(data.get("errors", [])):
        errors.append(_parse_error(raw, i))

    vocab_gaps = []
    for i, raw in enumerate(data.get("vocab_gaps", [])):
        vocab_gaps.append(_parse_vocab_gap(raw, i))

    word_count = data.get("word_count", 0)
    if not isinstance(word_count, int) or word_count < 0:
        raise SchemaError(f"word_count must be a non-negative integer, got {word_count!r}")

    return Session(
        session_id=str(_require(data, "session_id")),
        date=str(_require(data, "date")),
        schema_version=version,
        language=str(data.get("language", "en")),
        mode=_parse_mode(data),
        topics=list(data.get("topics", [])),
        notes=str(data.get("notes", "")),
        word_count=word_count,
        errors=errors,
        vocab_gaps=vocab_gaps,
    )


def _parse_mode(data: dict[str, Any]) -> str:
    mode = data.get("mode", DEFAULT_MODE)
    if not isinstance(mode, str) or mode not in MODES:
        raise SchemaError(f"mode must be one of {MODES}, got {mode!r}")
    return mode


def _parse_error(raw: Any, index: int) -> ErrorEntry:
    if not isinstance(raw, dict):
        raise SchemaError(f"errors[{index}] must be an object")
    etype = _require(raw, "type")
    if etype not in SUPPORTED_TYPES:
        raise SchemaError(
            f"errors[{index}].type must be one of {SUPPORTED_TYPES}, got {etype!r}"
        )

    self_caught = raw.get("self_caught", False)
    if not isinstance(self_caught, bool):
        raise SchemaError(f"errors[{index}].self_caught must be a boolean")

    return ErrorEntry(
        rule_id=str(_require(raw, "rule_id")),
        type=etype,
        quote=str(_require(raw, "quote")),
        fix=str(_require(raw, "fix")),
        self_caught=self_caught,
    )


def _parse_vocab_gap(raw: Any, index: int) -> VocabGap:
    if not isinstance(raw, dict):
        raise SchemaError(f"vocab_gaps[{index}] must be an object")
    return VocabGap(
        l1_word=str(_require(raw, "l1_word")),
        target_word=str(_require(raw, "target_word")),
        context=str(_require(raw, "context")),
        date=str(raw.get("date", "")),
    )
