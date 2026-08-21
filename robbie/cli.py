"""CLI for Robbie: the English coach.

Usage:
  robbie activate     start an interactive coach session
  robbie setup        write your LLM config (~/.config/robbie/config.toml)
  robbie show         dashboard: sessions, ratings, errors per 100 words
  robbie load         load session files into MongoDB
  robbie rules        sync rules catalog into MongoDB
"""

import argparse
import getpass
import sys
from pathlib import Path

from .activate import activate
from .config import DEFAULT_BASE_URL, DEFAULT_MODEL, ConfigError, write_config
from .db import DBError, RobbieDB
from .parser import SchemaError, parse_session_file


def cmd_activate(args) -> int:
    return activate()


MODELS_BY_PROVIDER = {
    "deepseek": ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
    "openrouter": ["deepseek/deepseek-chat", "anthropic/claude-3.5-sonnet", "openai/gpt-4o-mini"],
}


def _pick_model(base_url: str) -> str:
    """Offer a numbered model picker; fall back to free text for unknown providers."""
    options = None
    for provider, models in MODELS_BY_PROVIDER.items():
        if provider in base_url.lower():
            options = models
            break
    if options is None:
        return input(f"Model [{DEFAULT_MODEL}]: ").strip() or DEFAULT_MODEL

    print("\nSelect a model:")
    for i, m in enumerate(options, 1):
        print(f"  {i}. {m}")
    print(f"  {len(options) + 1}. custom")
    while True:
        try:
            choice = input(f"Model [1-{len(options) + 1}] (default 1): ").strip()
        except EOFError:
            choice = ""
        if choice == "":
            return options[0]
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(options):
                return options[idx - 1]
            if idx == len(options) + 1:
                custom = input("Custom model name: ").strip()
                if custom:
                    return custom
        print(f"  pick a number 1–{len(options) + 1}")


def cmd_setup(args) -> int:
    print(f"Writing config to ~/.config/robbie/config.toml")
    api_key = getpass.getpass("LLM API key: ").strip()
    if not api_key:
        print("robbie: no key given, aborting", file=sys.stderr)
        return 1
    base_url = input(f"API base URL [{DEFAULT_BASE_URL}]: ").strip() or DEFAULT_BASE_URL
    model = _pick_model(base_url)
    try:
        path = write_config(api_key, base_url, model)
    except OSError as exc:
        print(f"robbie: could not write config: {exc}", file=sys.stderr)
        return 1
    print(f"saved {path} (chmod 600)")
    return 0


def cmd_load(args) -> int:
    db = RobbieDB()
    paths = args.files or sorted(Path("sessions").glob("*.json"))
    loaded = 0
    for p in paths:
        try:
            session = parse_session_file(p)
        except SchemaError as exc:
            print(f"SKIP {p}: {exc}", file=sys.stderr)
            continue
        db.upsert_session(session)
        print(f"loaded {p} ({session.session_id}, rating {session.rating():.1f})")
        loaded += 1
    db.close()
    return 0


def cmd_show(args) -> int:
    db = RobbieDB()
    print(f"{'session':<14} {'date':<12} {'words':>5} {'rating':>6} {'err/100w':>9}  topics")
    print("-" * 72)
    for s in db.all_sessions():
        per_100 = s.errors_per_100_words()
        per_100_s = f"{per_100:.2f}" if per_100 is not None else "—"
        print(f"{s.session_id:<14} {s.date:<12} {s.word_count:>5} {s.rating():>6.1f} {per_100_s:>9}  {', '.join(s.topics)}")
    print("-" * 72)
    print("lifetime counts by rule:", db.counts_by_rule())
    print("lifetime counts by type:", db.counts_by_type())
    db.close()
    return 0


def cmd_rules(args) -> int:
    db = RobbieDB()
    summary = db.sync_rules(args.file)
    print(f"synced {summary['rules']} rules from {args.file}")
    orphans = summary["orphan_rule_ids"]
    if orphans:
        print(f"WARNING: rule_ids in errors without a catalog entry: {', '.join(orphans)}")
    else:
        print("all rule_ids in errors have a catalog entry")
    db.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="robbie")
    sub = parser.add_subparsers(dest="command", required=True)

    p_activate = sub.add_parser("activate", help="start an interactive coach session")
    p_activate.set_defaults(func=cmd_activate)

    p_setup = sub.add_parser("setup", help="write your LLM config")
    p_setup.set_defaults(func=cmd_setup)

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
    except (DBError, ConfigError) as exc:
        print(f"robbie: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
