"""MongoDB storage for Robbie.

Stores facts, never verdicts: a session's rating is NOT persisted. It is
recomputed on load from the current WEIGHTS in parser.py, so every past
session re-scores consistently when weights are tuned.

Two collections (per project_brainstorm.md):
  sessions  - one document per session (meta + vocab gaps), keyed by session_id
  errors    - one document per error entry, referencing session_id
"""

from datetime import datetime, timezone
from pathlib import Path

from pymongo import ASCENDING, MongoClient, errors

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
        self.errors.create_index([("session_id", ASCENDING)])

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

    def _to_session(self, doc: dict) -> Session:
        errors_docs = list(self.errors.find({"session_id": doc["_id"]}))
        return Session(
            session_id=doc["_id"],
            date=doc["date"],
            schema_version=doc.get("schema_version", 1),
            language=doc.get("language", "en"),
            topics=list(doc.get("topics", [])),
            notes=doc.get("notes", ""),
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
