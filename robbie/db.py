"""SQLite storage for Robbie (simplified branch).

Same public API as the PostgreSQL version, backed by the stdlib sqlite3
module — no Docker, no psycopg, no server to keep running. The database is a
single local file (robbie.db by default).

Stores facts, never verdicts: a session's rating is NOT persisted. It is
recomputed on load from the current WEIGHTS in parser.py, so every past
session re-scores consistently when weights are tuned.

Tables:
  sessions  - one row per session (meta + vocab gaps), keyed by session_id
  errors    - one row per error entry, referencing session_id (autoincrement
              id keeps insertion order)
  cards     - one row per (l1_word, target_word) vocab-gap pair. Facts
              (contexts, first/last_seen, times_gapped) + the SM-2 review
              state, which is mutable and must be persisted.
"""

import json
from datetime import date as date_cls
from pathlib import Path

import sqlite3

from . import sm2
from .parser import DEFAULT_MODE, Session

ROOT_DIR = Path(__file__).resolve().parents[1]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    date           TEXT NOT NULL,
    language       TEXT NOT NULL DEFAULT 'en',
    mode           TEXT NOT NULL DEFAULT 'casual',
    topics         TEXT NOT NULL DEFAULT '[]',
    notes          TEXT NOT NULL DEFAULT '',
    word_count     INTEGER NOT NULL DEFAULT 0,
    vocab_gaps     TEXT NOT NULL DEFAULT '[]',
    stored_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    type        TEXT NOT NULL,
    quote       TEXT NOT NULL,
    fix         TEXT NOT NULL,
    self_caught INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cards (
    slug          TEXT PRIMARY KEY,
    l1_word       TEXT NOT NULL,
    target_word   TEXT NOT NULL,
    contexts      TEXT NOT NULL DEFAULT '[]',
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    times_gapped  INTEGER NOT NULL DEFAULT 0,
    repetitions   INTEGER NOT NULL DEFAULT 0,
    ease_factor   REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 0,
    due_date      TEXT NOT NULL,
    last_reviewed TEXT,
    suspended     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_errors_session_id ON errors(session_id);
CREATE INDEX IF NOT EXISTS idx_cards_due_date ON cards(due_date);
"""


class DBError(RuntimeError):
    """Raised when storage can't be reached."""


class RobbieDB:
    def __init__(self, db_name: str = "robbie", dsn: str | None = None) -> None:
        path = Path(dsn) if dsn else ROOT_DIR / f"{db_name}.db"
        try:
            self._conn = sqlite3.connect(str(path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as exc:
            raise DBError(f"cannot open SQLite database {path}: {exc}") from exc
        self._init_schema()

    def _init_schema(self) -> None:
        try:
            self._conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            raise DBError(f"could not initialise schema: {exc}") from exc

    def close(self) -> None:
        self._conn.close()

    def clear(self) -> None:
        """Delete all rows (used by tests to reset state)."""
        self._conn.execute("DELETE FROM errors")
        self._conn.execute("DELETE FROM cards")
        self._conn.execute("DELETE FROM sessions")
        self._conn.commit()

    def upsert_session(self, session: Session) -> None:
        """Persist a session and its errors. Replaces any previous version."""
        self._conn.execute(
            """
            INSERT INTO sessions (
                session_id, schema_version, date, language, mode, topics,
                notes, word_count, vocab_gaps, stored_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET
                schema_version = excluded.schema_version,
                date           = excluded.date,
                language       = excluded.language,
                mode           = excluded.mode,
                topics         = excluded.topics,
                notes          = excluded.notes,
                word_count     = excluded.word_count,
                vocab_gaps     = excluded.vocab_gaps,
                stored_at      = excluded.stored_at
            """,
            (
                session.session_id,
                session.schema_version,
                _to_iso(session.date),
                session.language,
                session.mode,
                json.dumps(list(session.topics)),
                session.notes,
                session.word_count,
                json.dumps(
                    [
                        {
                            "l1_word": gap.l1_word,
                            "target_word": gap.target_word,
                            "context": gap.context,
                            "date": gap.date,
                        }
                        for gap in session.vocab_gaps
                    ]
                ),
                _now(),
            ),
        )
        self._conn.execute(
            "DELETE FROM errors WHERE session_id = ?", (session.session_id,)
        )
        if session.errors:
            self._conn.executemany(
                """
                INSERT INTO errors (session_id, type, quote, fix, self_caught)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        session.session_id,
                        e.type,
                        e.quote,
                        e.fix,
                        1 if e.self_caught else 0,
                    )
                    for e in session.errors
                ],
            )
        self._conn.commit()

    def get_session(self, session_id: str) -> Session | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return self._to_session(row)

    def all_sessions(self) -> list[Session]:
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY date, session_id"
        ).fetchall()
        return [self._to_session(row) for row in rows]

    def counts_by_type(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT type, COUNT(*) AS total FROM errors GROUP BY type"
        ).fetchall()
        return {row["type"]: row["total"] for row in rows}

    def session_ids_on(self, date: str) -> list[str]:
        """Session ids for a given day (for `next_session_id`)."""
        rows = self._conn.execute(
            "SELECT session_id FROM sessions WHERE date = ?", (_to_iso(date),)
        ).fetchall()
        return [row["session_id"] for row in rows]

    def sync_cards_from_session(self, session: Session) -> int:
        """Upsert one card per (l1_word, target_word) gap in a session.

        New pair → create a card, due immediately. Existing pair → append the
        context (once per session) and bump times_gapped. Returns how many
        cards were touched.
        """
        by_slug: dict[str, list] = {}
        for gap in session.vocab_gaps:
            slug = sm2.card_slug(gap.l1_word, gap.target_word)
            by_slug.setdefault(slug, []).append(gap)

        for slug, gaps in by_slug.items():
            first = gaps[0]
            date = first.date or session.date
            row = self._conn.execute(
                "SELECT * FROM cards WHERE slug = ?", (slug,)
            ).fetchone()

            if row is None:
                doc = {
                    "slug": slug,
                    "l1_word": first.l1_word,
                    "target_word": first.target_word,
                    "contexts": [],
                    "first_seen": date,
                    "last_seen": date,
                    "times_gapped": 0,
                    "repetitions": 0,
                    "ease_factor": sm2.EASE_FACTOR_INIT,
                    "interval_days": 0,
                    "due_date": date,
                    "last_reviewed": None,
                    "suspended": False,
                }
            else:
                doc = _card_from_row(row)

            seen = {(c["session_id"], c["context"]) for c in doc["contexts"]}
            new_contexts = []
            added = 0
            for gap in gaps:
                key = (session.session_id, gap.context)
                if key in seen:
                    continue
                seen.add(key)
                new_contexts.append(
                    {
                        "session_id": session.session_id,
                        "date": gap.date or session.date,
                        "context": gap.context,
                    }
                )
                added += 1
            doc["contexts"].extend(new_contexts)
            doc["times_gapped"] += added
            if date > doc["last_seen"]:
                doc["last_seen"] = date

            self._conn.execute(
                """
                INSERT INTO cards (
                    slug, l1_word, target_word, contexts, first_seen, last_seen,
                    times_gapped, repetitions, ease_factor, interval_days,
                    due_date, last_reviewed, suspended
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (slug) DO UPDATE SET
                    contexts     = excluded.contexts,
                    times_gapped = excluded.times_gapped,
                    last_seen    = MAX(cards.last_seen, excluded.last_seen)
                """,
                (
                    doc["slug"],
                    doc["l1_word"],
                    doc["target_word"],
                    json.dumps(doc["contexts"]),
                    _to_iso(doc["first_seen"]),
                    _to_iso(doc["last_seen"]),
                    doc["times_gapped"],
                    doc["repetitions"],
                    doc["ease_factor"],
                    doc["interval_days"],
                    _to_iso(doc["due_date"]),
                    _to_iso(doc["last_reviewed"]),
                    1 if doc["suspended"] else 0,
                ),
            )

        self._conn.commit()
        return len(by_slug)

    def get_card(self, slug: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM cards WHERE slug = ?", (slug,)
        ).fetchone()
        return _card_from_row(row) if row else None

    def all_cards(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM cards ORDER BY l1_word").fetchall()
        return [_card_from_row(row) for row in rows]

    def due_cards(self, today: str) -> list[dict]:
        """Cards scheduled on or before `today`, excluding suspended ones."""
        rows = self._conn.execute(
            """
            SELECT * FROM cards
            WHERE due_date <= ? AND NOT suspended
            ORDER BY due_date
            """,
            (_to_iso(today),),
        ).fetchall()
        return [_card_from_row(row) for row in rows]

    def count_due_cards(self, today: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS total FROM cards WHERE due_date <= ? AND NOT suspended",
            (_to_iso(today),),
        ).fetchone()
        return row["total"]

    def review_card(self, slug: str, grade: str, today: str) -> dict:
        """Apply an SM-2 grade to a card and persist the new state."""
        row = self._conn.execute(
            "SELECT * FROM cards WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no card with id {slug!r}")

        doc = _card_from_row(row)
        state = sm2.CardState(
            repetitions=doc["repetitions"],
            ease_factor=doc["ease_factor"],
            interval_days=doc["interval_days"],
        )
        new = state.with_review(grade, date_cls.fromisoformat(today))
        self._conn.execute(
            """
            UPDATE cards SET
                repetitions   = ?,
                ease_factor   = ?,
                interval_days = ?,
                due_date      = ?,
                last_reviewed = ?
            WHERE slug = ?
            """,
            (
                new.repetitions,
                round(new.ease_factor, 2),
                new.interval_days,
                _to_iso(new.due_date),
                _to_iso(new.last_reviewed),
                slug,
            ),
        )
        self._conn.commit()
        return self._card_from_row(self._conn.execute(
            "SELECT * FROM cards WHERE slug = ?", (slug,)
        ).fetchone())

    def card_status(self, doc: dict) -> str:
        """Derived status — stored as a verdict, so never persisted."""
        state = sm2.CardState(
            repetitions=doc.get("repetitions", 0),
            ease_factor=doc.get("ease_factor", sm2.EASE_FACTOR_INIT),
            interval_days=doc.get("interval_days", 0),
        )
        return state.status(suspended=doc.get("suspended", False))

    def _to_session(self, row: sqlite3.Row) -> Session:
        errors_rows = self._conn.execute(
            "SELECT * FROM errors WHERE session_id = ? ORDER BY id",
            (row["session_id"],),
        ).fetchall()
        data = dict(row)
        return Session(
            session_id=data["session_id"],
            date=data["date"],
            schema_version=data.get("schema_version", 1),
            language=data.get("language", "en"),
            mode=data.get("mode", DEFAULT_MODE),
            topics=list(_json_list(data.get("topics"))),
            notes=data.get("notes", ""),
            word_count=data.get("word_count", 0),
            errors=[_error_from_row(e) for e in errors_rows],
            vocab_gaps=[_gap_from_doc(g) for g in _json_list(data.get("vocab_gaps"))],
        )

    def _card_from_row(self, row: sqlite3.Row) -> dict:
        return _card_from_row(row)


def _card_from_row(row: sqlite3.Row) -> dict:
    return {
        "slug": row["slug"],
        "l1_word": row["l1_word"],
        "target_word": row["target_word"],
        "contexts": _json_list(row["contexts"]),
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "times_gapped": row["times_gapped"],
        "repetitions": row["repetitions"],
        "ease_factor": row["ease_factor"],
        "interval_days": row["interval_days"],
        "due_date": row["due_date"],
        "last_reviewed": row["last_reviewed"],
        "suspended": bool(row["suspended"]),
    }


def _json_list(value) -> list:
    """Decode a JSON array column into a Python list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _error_from_row(row: sqlite3.Row):
    from .parser import ErrorEntry

    data = dict(row)
    return ErrorEntry(
        type=data["type"],
        quote=data["quote"],
        fix=data["fix"],
        self_caught=bool(data.get("self_caught", False)),
    )


def _gap_from_doc(doc: dict):
    from .parser import VocabGap

    return VocabGap(
        l1_word=doc["l1_word"],
        target_word=doc["target_word"],
        context=doc["context"],
        date=doc.get("date", ""),
    )


def _to_iso(value) -> str | None:
    """Normalise a date/datetime/ISO string into ISO text for SQLite."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
