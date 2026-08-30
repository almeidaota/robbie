"""PostgreSQL storage for Robbie.

Stores facts, never verdicts: a session's rating is NOT persisted. It is
recomputed on load from the current WEIGHTS in parser.py, so every past
session re-scores consistently when weights are tuned.

Tables (per project_brainstorm.md):
  sessions  - one row per session (meta + vocab gaps), keyed by session_id
  errors    - one row per error entry, referencing session_id (id serial keeps
              insertion order, the Postgres answer to Mongo's ObjectId)
  cards     - one row per (l1_word, target_word) vocab-gap pair. Facts
              (contexts, first/last_seen, times_gapped) + the SM-2 review
              state, which is mutable and must be persisted.

Credentials come from the repo-root .env (POSTGRES_HOST, POSTGRES_PORT,
POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB) — never hardcoded.
"""

import os
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import sm2
from .parser import DEFAULT_MODE, Session

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

DEFAULT_DB = "robbie"


class DBError(RuntimeError):
    """Raised when storage can't be reached."""


class RobbieDB:
    def __init__(self, db_name: str = DEFAULT_DB, dsn: str | None = None) -> None:
        self._db_name = db_name
        self._auth = None
        self._dsn = dsn
        if dsn is None:
            self._auth = {
                "host": os.environ.get("POSTGRES_HOST", "localhost"),
                "port": int(os.environ.get("POSTGRES_PORT", "5432")),
                "user": os.environ.get("POSTGRES_USER", "robbie"),
                "password": os.environ.get("POSTGRES_PASSWORD", "robbie"),
            }
        _ensure_database(self._dsn, self._auth, db_name)
        try:
            self._conn = self._connect(db_name)
        except psycopg.OperationalError as exc:
            where = self._dsn or f"{self._auth['host']}:{self._auth['port']}"
            raise DBError(f"cannot reach PostgreSQL at {where}: {exc}") from exc
        self._init_schema()

    def _connect(self, db_name: str):
        if self._auth is not None:
            return psycopg.connect(
                dbname=db_name,
                connect_timeout=3,
                autocommit=True,
                row_factory=dict_row,
                **self._auth,
            )
        return psycopg.connect(
            self._dsn, connect_timeout=3, autocommit=True, row_factory=dict_row
        )

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id     TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL DEFAULT 1,
                date           DATE NOT NULL,
                language       TEXT NOT NULL DEFAULT 'en',
                mode           TEXT NOT NULL DEFAULT 'casual',
                topics         JSONB NOT NULL DEFAULT '[]'::jsonb,
                notes          TEXT NOT NULL DEFAULT '',
                word_count     INTEGER NOT NULL DEFAULT 0,
                vocab_gaps     JSONB NOT NULL DEFAULT '[]'::jsonb,
                stored_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS errors (
                id          SERIAL PRIMARY KEY,
                session_id  TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                type        TEXT NOT NULL,
                quote       TEXT NOT NULL,
                fix         TEXT NOT NULL,
                self_caught BOOLEAN NOT NULL DEFAULT false
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cards (
                slug          TEXT PRIMARY KEY,
                l1_word       TEXT NOT NULL,
                target_word   TEXT NOT NULL,
                contexts      JSONB NOT NULL DEFAULT '[]'::jsonb,
                first_seen    DATE NOT NULL,
                last_seen     DATE NOT NULL,
                times_gapped  INTEGER NOT NULL DEFAULT 0,
                repetitions   INTEGER NOT NULL DEFAULT 0,
                ease_factor   DOUBLE PRECISION NOT NULL DEFAULT 2.5,
                interval_days INTEGER NOT NULL DEFAULT 0,
                due_date      DATE NOT NULL,
                last_reviewed DATE,
                suspended     BOOLEAN NOT NULL DEFAULT false
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_errors_session_id ON errors(session_id)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_due_date ON cards(due_date)")

    def close(self) -> None:
        self._conn.close()

    def clear(self) -> None:
        """Truncate all tables (used by tests to reset state)."""
        self._conn.execute("TRUNCATE errors, cards, sessions RESTART IDENTITY")

    def upsert_session(self, session: Session) -> None:
        """Persist a session and its errors. Replaces any previous version."""
        self._conn.execute(
            """
            INSERT INTO sessions (
                session_id, schema_version, date, language, mode, topics,
                notes, word_count, vocab_gaps, stored_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE SET
                schema_version = EXCLUDED.schema_version,
                date           = EXCLUDED.date,
                language       = EXCLUDED.language,
                mode           = EXCLUDED.mode,
                topics         = EXCLUDED.topics,
                notes          = EXCLUDED.notes,
                word_count     = EXCLUDED.word_count,
                vocab_gaps     = EXCLUDED.vocab_gaps,
                stored_at      = EXCLUDED.stored_at
            """,
            (
                session.session_id,
                session.schema_version,
                _to_date(session.date),
                session.language,
                session.mode,
                Jsonb(list(session.topics)),
                session.notes,
                session.word_count,
                Jsonb(
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
                datetime.now(timezone.utc),
            ),
        )
        self._conn.execute(
            "DELETE FROM errors WHERE session_id = %s", (session.session_id,)
        )
        if session.errors:
            self._conn.cursor().executemany(
                """
                INSERT INTO errors (session_id, type, quote, fix, self_caught)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        session.session_id,
                        e.type,
                        e.quote,
                        e.fix,
                        e.self_caught,
                    )
                    for e in session.errors
                ],
            )

    def get_session(self, session_id: str) -> Session | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = %s", (session_id,)
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
            "SELECT session_id FROM sessions WHERE date = %s", (_to_date(date),)
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
                "SELECT * FROM cards WHERE slug = %s", (slug,)
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
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET
                    contexts     = EXCLUDED.contexts,
                    times_gapped = EXCLUDED.times_gapped,
                    last_seen    = GREATEST(cards.last_seen, EXCLUDED.last_seen)
                """,
                (
                    doc["slug"],
                    doc["l1_word"],
                    doc["target_word"],
                    Jsonb(doc["contexts"]),
                    _to_date(doc["first_seen"]),
                    _to_date(doc["last_seen"]),
                    doc["times_gapped"],
                    doc["repetitions"],
                    doc["ease_factor"],
                    doc["interval_days"],
                    _to_date(doc["due_date"]),
                    _to_date(doc["last_reviewed"]),
                    doc["suspended"],
                ),
            )

        return len(by_slug)

    def get_card(self, slug: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM cards WHERE slug = %s", (slug,)
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
            WHERE due_date <= %s AND NOT suspended
            ORDER BY due_date
            """,
            (_to_date(today),),
        ).fetchall()
        return [_card_from_row(row) for row in rows]

    def count_due_cards(self, today: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS total FROM cards WHERE due_date <= %s AND NOT suspended",
            (_to_date(today),),
        ).fetchone()
        return row["total"]

    def review_card(self, slug: str, grade: str, today: str) -> dict:
        """Apply an SM-2 grade to a card and persist the new state."""
        row = self._conn.execute(
            "SELECT * FROM cards WHERE slug = %s", (slug,)
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
        updated = self._conn.execute(
            """
            UPDATE cards SET
                repetitions   = %s,
                ease_factor   = %s,
                interval_days = %s,
                due_date      = %s,
                last_reviewed = %s
            WHERE slug = %s
            RETURNING *
            """,
            (
                new.repetitions,
                round(new.ease_factor, 2),
                new.interval_days,
                new.due_date,
                new.last_reviewed,
                slug,
            ),
        ).fetchone()
        return _card_from_row(updated)

    def card_status(self, doc: dict) -> str:
        """Derived status — stored as a verdict, so never persisted."""
        state = sm2.CardState(
            repetitions=doc.get("repetitions", 0),
            ease_factor=doc.get("ease_factor", sm2.EASE_FACTOR_INIT),
            interval_days=doc.get("interval_days", 0),
        )
        return state.status(suspended=doc.get("suspended", False))

    def _to_session(self, row: dict) -> Session:
        errors_rows = self._conn.execute(
            "SELECT * FROM errors WHERE session_id = %s ORDER BY id",
            (row["session_id"],),
        ).fetchall()
        return Session(
            session_id=row["session_id"],
            date=row["date"].isoformat(),
            schema_version=row.get("schema_version", 1),
            language=row.get("language", "en"),
            mode=row.get("mode", DEFAULT_MODE),
            topics=list(row.get("topics", [])),
            notes=row.get("notes", ""),
            word_count=row.get("word_count", 0),
            errors=[_error_from_row(e) for e in errors_rows],
            vocab_gaps=[_gap_from_doc(g) for g in row.get("vocab_gaps", [])],
        )


def _ensure_database(dsn: str | None, auth: dict | None, db_name: str) -> None:
    """Create the target database if it doesn't exist yet (dev convenience)."""
    if db_name == "postgres":
        return
    try:
        if auth is not None:
            conn = psycopg.connect(
                dbname="postgres", connect_timeout=3, autocommit=True, **auth
            )
        else:
            conn = psycopg.connect(dsn, connect_timeout=3, autocommit=True)
    except psycopg.OperationalError:
        return
    try:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        conn.close()


def _card_from_row(row: dict) -> dict:
    return {
        "slug": row["slug"],
        "l1_word": row["l1_word"],
        "target_word": row["target_word"],
        "contexts": row["contexts"],
        "first_seen": row["first_seen"].isoformat(),
        "last_seen": row["last_seen"].isoformat(),
        "times_gapped": row["times_gapped"],
        "repetitions": row["repetitions"],
        "ease_factor": row["ease_factor"],
        "interval_days": row["interval_days"],
        "due_date": row["due_date"].isoformat(),
        "last_reviewed": (
            row["last_reviewed"].isoformat() if row["last_reviewed"] else None
        ),
        "suspended": row["suspended"],
    }


def _error_from_row(row: dict):
    from .parser import ErrorEntry

    return ErrorEntry(
        type=row["type"],
        quote=row["quote"],
        fix=row["fix"],
        self_caught=row.get("self_caught", False),
    )


def _gap_from_doc(doc: dict):
    from .parser import VocabGap

    return VocabGap(
        l1_word=doc["l1_word"],
        target_word=doc["target_word"],
        context=doc["context"],
        date=doc.get("date", ""),
    )


def _to_date(value: str | None):
    if value is None:
        return None
    return date_cls.fromisoformat(value)
