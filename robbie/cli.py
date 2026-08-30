"""CLI for Robbie: the English coach.

Usage:
  robbie activate     start an interactive coach session
  robbie setup        write your LLM config (~/.config/robbie/config.toml)
  robbie show         dashboard: sessions, ratings, errors per 100 words
  robbie review       spaced-repetition review of your vocab-gap cards
  robbie export       build an Anki .apkg from the vocab cards
"""

import argparse
import getpass
import os
import sys

from .activate import activate
from .config import DEFAULT_BASE_URL, DEFAULT_MODEL, ConfigError, write_config
from .db import DBError, RobbieDB
from .export import build_deck, export
from .parser import MODES
from .review import review


def cmd_activate(args) -> int:
    return activate(mode=args.mode)


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
    print("Writing config to .env")
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
    print(f"saved {path}")
    if os.name != "nt":
        print("(permissions restricted to owner)")
    return 0


def cmd_show(args) -> int:
    db = RobbieDB()
    print(f"{'session':<14} {'date':<12} {'mode':<10} {'words':>5} {'rating':>6} {'err/100w':>9}  topics")
    print("-" * 80)
    for s in db.all_sessions():
        per_100 = s.errors_per_100_words()
        per_100_s = f"{per_100:.2f}" if per_100 is not None else "—"
        print(f"{s.session_id:<14} {s.date:<12} {s.mode:<10} {s.word_count:>5} {s.rating():>6.1f} {per_100_s:>9}  {', '.join(s.topics)}")
    print("-" * 80)
    print("lifetime counts by type:", db.counts_by_type())
    db.close()
    return 0


def cmd_review(args) -> int:
    return review()


def cmd_export(args) -> int:
    db = RobbieDB()
    cards = db.all_cards()
    db.close()
    if not cards:
        print("robbie: no vocab cards to export — gaps appear after a session")
        return 0
    deck = build_deck(cards)
    path = export(deck, args.output)
    print(f"exported {len(deck.notes)} card(s) to {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="robbie")
    sub = parser.add_subparsers(dest="command", required=True)

    p_activate = sub.add_parser("activate", help="start an interactive coach session")
    p_activate.add_argument(
        "--mode",
        choices=MODES,
        default="casual",
        help="coach mode for the whole session (default: casual)",
    )
    p_activate.set_defaults(func=cmd_activate)

    p_setup = sub.add_parser("setup", help="write your LLM config")
    p_setup.set_defaults(func=cmd_setup)

    p_show = sub.add_parser("show", help="show stored sessions with recomputed ratings")
    p_show.set_defaults(func=cmd_show)

    p_review = sub.add_parser("review", help="spaced-repetition review of vocab-gap cards")
    p_review.set_defaults(func=cmd_review)

    p_export = sub.add_parser("export", help="build an Anki .apkg from the vocab cards")
    p_export.add_argument(
        "output",
        nargs="?",
        default="robbie_vocab.apkg",
        help="output .apkg path (default: robbie_vocab.apkg)",
    )
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (DBError, ConfigError) as exc:
        print(f"robbie: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
