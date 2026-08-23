"""SM-2 spaced repetition — the algorithm Anki is built on. Pure and deterministic.

Only math lives here. Given a card's persisted state and a grade, produce the
next state. No judgment calls, no IO. The caller (robbie/db.py) stores the
state; the SM-2 state is mutable and must be persisted because it can't be
recomputed from the vocab-gap facts.
"""

from dataclasses import dataclass
from datetime import date

EASE_FACTOR_INIT = 2.5
MIN_EASE_FACTOR = 1.3

# Grade → ease adjustment (Anki-ish). Again is punishing, Easy is a bonus.
EASE_DELTA = {"again": -0.20, "hard": -0.15, "good": 0.00, "easy": 0.15}

GRADES = tuple(EASE_DELTA)

# Multipliers applied on top of interval * ease for Hard / Easy.
HARD_INTERVAL_MULTIPLIER = 1.2
EASY_INTERVAL_MULTIPLIER = 1.3

# A new card's first interval, per grade.
FIRST_INTERVAL = {"hard": 1, "good": 1, "easy": 2}

# Graduation thresholds for the derived status.
LEARNING_REPETITIONS = 3   # repetitions before a card leaves "learning"
MATURE_INTERVAL = 21       # days before a card becomes "mature"


@dataclass
class CardState:
    repetitions: int = 0
    ease_factor: float = EASE_FACTOR_INIT
    interval_days: int = 0
    due_date: date | None = None
    last_reviewed: date | None = None

    def with_review(self, grade: str, today: date) -> "CardState":
        if grade not in GRADES:
            raise ValueError(f"grade must be one of {GRADES}, got {grade!r}")

        ease = max(MIN_EASE_FACTOR, self.ease_factor + EASE_DELTA[grade])

        if self.repetitions == 0:
            if grade == "again":
                return CardState(0, ease, 0, today, today)
            reps, interval = 1, FIRST_INTERVAL[grade]
        elif grade == "again":
            return CardState(0, ease, 0, today, today)
        elif grade == "hard":
            reps = self.repetitions + 1
            interval = _grow(self.interval_days, HARD_INTERVAL_MULTIPLIER)
        elif grade == "good":
            reps = self.repetitions + 1
            interval = _grow(self.interval_days, ease)
        else:  # easy
            reps = self.repetitions + 1
            interval = _grow(self.interval_days, ease * EASY_INTERVAL_MULTIPLIER)

        return CardState(reps, ease, interval, today, today)

    def status(self, suspended: bool = False) -> str:
        if suspended:
            return "suspended"
        if self.repetitions < LEARNING_REPETITIONS:
            return "learning"
        if self.interval_days < MATURE_INTERVAL:
            return "reviewing"
        return "mature"


def _grow(interval_days: int, factor: float) -> int:
    """Next interval: at least a day longer than the current one."""
    return max(interval_days + 1, round(interval_days * factor))


def card_slug(l1_word: str, target_word: str) -> str:
    """Stable id for the (l1_word, target_word) pair, e.g. 'atualize->update'."""
    return f"{_norm(l1_word)}->{_norm(target_word)}"


def _norm(word: str) -> str:
    return " ".join(word.strip().lower().split())
