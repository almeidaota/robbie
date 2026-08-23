"""MongoDB storage for Robbie.

Stores facts, never verdicts: a session's rating is NOT persisted. It is
recomputed on load from the current WEIGHTS in parser.py, so every past
session re-scores consistently when weights are tuned.

Collections (per project_brainstorm.md):
  sessions  - one document per session (meta + vocab gaps), keyed by session_id
  errors    - one document per error entry, referencing session_id
  rules     - the catalog synced from common_mistakes.md
  cards     - one document per (l1_word, target_word) vocab-gap pair. Facts
              (contexts, first/last_seen, times_gapped) + the SM-2 review
              state, which is mutable and must be persisted.
"""

from datetime import datetime, timezone
from pathlib import Path

from pymongo import ASCENDING, MongoClient, errors

from . import sm2
from .parser import Session

DEFAULT_URI = "mongodb://localhost:27017"
DEFAULT_DB = "robbie"


class DBError(RuntimeError):
    """Raised when storage can't be reached."""


class RobbieDB:
    def __init__(self, uri: str = DEFAULT_URI, db_name: str = DEFAULT_DB) -> None:
        self._client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        try:
            self._client.admin.command("ping")
        except errors.PyMongoError as exc:
            self._client.close()
            raise DBError(f"cannot reach MongoDB at {uri}: {exc}") from exc
        self.db = self._client[db_name]
        self.sessions = self.db["sessions"]
        self.errors = self.db["errors"]
        self.rules = self.db["rules"]
        self.cards = self.db["cards"]
        self.errors.create_index([("session_id", ASCENDING)])
        self.cards.create_index([("due_date", ASCENDING)])

    def close(self) -> None:
        self._client.close()

    def upsert_session(self, session: Session) -> None:
        """Persist a session and its errors. Replaces any previous version."""
        session_doc = {
            "_id": session.session_id,
            "schema_version": session.schema_version,
            "date": session.date,
            "language": session.language,
            "topics": list(session.topics),
            "notes": session.notes,
            "word_count": session.word_count,
            "vocab_gaps": [
                {
                    "l1_word": gap.l1_word,
                    "target_word": gap.target_word,
                    "context": gap.context,
                    "date": gap.date,
                }
                for gap in session.vocab_gaps
            ],
            "stored_at": datetime.now(timezone.utc),
        }
        self.sessions.replace_one({"_id": session.session_id}, session_doc, upsert=True)
        self.errors.delete_many({"session_id": session.session_id})
        if session.errors:
            self.errors.insert_many(
                [
                    {
                        "session_id": session.session_id,
                        "rule_id": e.rule_id,
                        "type": e.type,
                        "quote": e.quote,
                        "fix": e.fix,
                        "self_caught": e.self_caught,
                    }
                    for e in session.errors
                ]
            )

    def get_session(self, session_id: str) -> Session | None:
        doc = self.sessions.find_one({"_id": session_id})
        if doc is None:
            return None
        return self._to_session(doc)

    def all_sessions(self) -> list[Session]:
        docs = self.sessions.find().sort("date", ASCENDING)
        return [self._to_session(doc) for doc in docs]

    def counts_by_rule(self) -> dict[str, int]:
        """Lifetime error counts grouped by rule. The counters as a query."""
        pipeline = [{"$group": {"_id": "$rule_id", "total": {"$sum": 1}}}]
        return {d["_id"]: d["total"] for d in self.errors.aggregate(pipeline)}

    def counts_by_type(self) -> dict[str, int]:
        pipeline = [{"$group": {"_id": "$type", "total": {"$sum": 1}}}]
        return {d["_id"]: d["total"] for d in self.errors.aggregate(pipeline)}

    def sync_rules(self, path: str | Path) -> dict:
        """Replace the rules collection from the catalog. Returns a summary."""
        from .rules import RulesError, parse_rules_file

        rules = parse_rules_file(path)
        self.rules.delete_many({})
        if rules:
            self.rules.insert_many([r.to_doc() for r in rules])
        return {
            "rules": len(rules),
            "orphan_rule_ids": self.orphan_rule_ids(),
        }

    def orphan_rule_ids(self) -> list[str]:
        """rule_ids used in errors but missing from the catalog."""
        used = self.errors.distinct("rule_id")
        known = set(self.rules.distinct("rule_id"))
        return sorted(rid for rid in used if rid not in known)

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
            doc = self.cards.find_one({"_id": slug})

            if doc is None:
                doc = {
                    "_id": slug,
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
            if date > doc.get("last_seen", ""):
                doc["last_seen"] = date
            self.cards.replace_one({"_id": slug}, doc, upsert=True)

        return len(by_slug)

    def get_card(self, slug: str) -> dict | None:
        return self.cards.find_one({"_id": slug})

    def all_cards(self) -> list[dict]:
        return list(self.cards.find().sort("l1_word", ASCENDING))

    def due_cards(self, today: str) -> list[dict]:
        """Cards scheduled on or before `today`, excluding suspended ones."""
        return list(
            self.cards.find({"due_date": {"$lte": today}, "suspended": False}).sort(
                "due_date", ASCENDING
            )
        )

    def review_card(self, slug: str, grade: str, today: str) -> dict:
        """Apply an SM-2 grade to a card and persist the new state."""
        from datetime import date as date_cls

        doc = self.cards.find_one({"_id": slug})
        if doc is None:
            raise KeyError(f"no card with id {slug!r}")

        today = date_cls.fromisoformat(today)
        state = sm2.CardState(
            repetitions=doc.get("repetitions", 0),
            ease_factor=doc.get("ease_factor", sm2.EASE_FACTOR_INIT),
            interval_days=doc.get("interval_days", 0),
        )
        new = state.with_review(grade, today)
        self.cards.update_one(
            {"_id": slug},
            {
                "$set": {
                    "repetitions": new.repetitions,
                    "ease_factor": round(new.ease_factor, 2),
                    "interval_days": new.interval_days,
                    "due_date": new.due_date.isoformat(),
                    "last_reviewed": new.last_reviewed.isoformat(),
                }
            },
        )
        return self.cards.find_one({"_id": slug})

    def card_status(self, doc: dict) -> str:
        """Derived status — stored as a verdict, so never persisted."""
        state = sm2.CardState(
            repetitions=doc.get("repetitions", 0),
            ease_factor=doc.get("ease_factor", sm2.EASE_FACTOR_INIT),
            interval_days=doc.get("interval_days", 0),
        )
        return state.status(suspended=doc.get("suspended", False))

    def _to_session(self, doc: dict) -> Session:
        errors_docs = list(self.errors.find({"session_id": doc["_id"]}))
        return Session(
            session_id=doc["_id"],
            date=doc["date"],
            schema_version=doc.get("schema_version", 1),
            language=doc.get("language", "en"),
            topics=list(doc.get("topics", [])),
            notes=doc.get("notes", ""),
            word_count=doc.get("word_count", 0),
            errors=[
                _error_from_doc(e)
                for e in sorted(errors_docs, key=lambda e: e["_id"])
            ],
            vocab_gaps=[
                _gap_from_doc(g)
                for g in doc.get("vocab_gaps", [])
            ],
        )


def _error_from_doc(doc: dict):
    from .parser import ErrorEntry

    return ErrorEntry(
        rule_id=doc["rule_id"],
        type=doc["type"],
        quote=doc["quote"],
        fix=doc["fix"],
        self_caught=doc.get("self_caught", False),
    )


def _gap_from_doc(doc: dict):
    from .parser import VocabGap

    return VocabGap(
        l1_word=doc["l1_word"],
        target_word=doc["target_word"],
        context=doc["context"],
        date=doc.get("date", ""),
    )
