"""CLI for Robbie's storage: load session files into MongoDB and query them.

Usage:
  python -m robbie.cli load [sessions/...]
  python -m robbie.cli show
"""

import argparse
import sys
from pathlib import Path

from .parser import SchemaError, parse_session_file
from .db import DBError, RobbieDB


def cmd_load(args) -> int:
    store = RobbieDB()
    paths = args.files or sorted(Path("sessions").glob("*.json"))
    loaded = 0
    for p in paths:
        try:
            session = parse_session_file(p)
        except SchemaError as exc:
            print(f"SKIP {p}: {exc}", file=sys.stderr)
            continue
        store.upsert_session(session)
        print(f"loaded {p} ({session.session_id}, rating {session.rating():.1f})")
        loaded += 1
    store.close()
    return 0


def cmd_show(args) -> int:
    store = RobbieDB()
    print(f"{'session':<14} {'date':<12} {'rating':>6}  topics")
    print("-" * 60)
    for s in store.all_sessions():
        print(f"{s.session_id:<14} {s.date:<12} {s.rating():>6.1f}  {', '.join(s.topics)}")
    print("-" * 60)
    print("lifetime counts by rule:", store.counts_by_rule())
    print("lifetime counts by type:", store.counts_by_type())
    store.close()
    return 0


def cmd_rules(args) -> int:
    store = RobbieDB()
    summary = store.sync_rules(args.file)
    print(f"synced {summary['rules']} rules from {args.file}")
    orphans = summary["orphan_rule_ids"]
    if orphans:
        print(f"WARNING: rule_ids in errors without a catalog entry: {', '.join(orphans)}")
    else:
        print("all rule_ids in errors have a catalog entry")
    store.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="robbie")
    sub = parser.add_subparsers(dest="command", required=True)

    p_load = sub.add_parser("load", help="load session files into MongoDB")
    p_load.add_argument("files", nargs="*", help="session JSON files (default: sessions/*.json)")
    p_load.set_defaults(func=cmd_load)

    p_show = sub.add_parser("show", help="show stored sessions with recomputed ratings")
    p_show.set_defaults(func=cmd_show)

    p_rules = sub.add_parser("rules", help="sync rules collection from common_mistakes.md")
    p_rules.add_argument(
        "file",
        nargs="?",
        default="robbie_brain/common_mistakes.md",
        help="rules catalog path (default: robbie_brain/common_mistakes.md)",
    )
    p_rules.set_defaults(func=cmd_rules)

    args = parser.parse_args()
    try:
        return args.func(args)
    except DBError as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
