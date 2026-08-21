"""`robbie activate` — the interactive coach session.

Chat loop: reads user input, streams coach replies, counts the user's words
as they type. On /quit, asks the coach for the session JSON, validates it
against the schema, stores it, and appends a human summary to session_log.md.
"""

import json
import sys
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from .coach import RULES_FILE, Coach, CoachError, append_session_log
from .config import ConfigError, load_config
from .db import DBError, RobbieDB
from .llm import LLMClient, LLMError
from .parser import parse_session_file
from .rules import RulesError

SESSIONS_DIR = Path("sessions")

console = Console()


def next_session_id() -> str:
    """date + counter, e.g. 2026-08-21-03 (deterministic per existing files)."""
    today = date.today().isoformat()
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    same_day = [p.stem for p in SESSIONS_DIR.glob(f"{today}-*.json")]
    counts = []
    for stem in same_day:
        try:
            counts.append(int(stem.rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    return f"{today}-{max(counts, default=0) + 1:02d}"


def activate() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        console.print(f"[red]robbie:[/] {exc}")
        return 1

    try:
        db = RobbieDB()
    except DBError as exc:
        console.print(f"[red]robbie:[/] {exc}")
        console.print("is the database up? try: docker compose up -d")
        return 1

    llm = LLMClient(config)
    coach = Coach(llm, db)
    session_id = next_session_id()

    history: list[dict] = [{"role": "system", "content": coach.system_prompt()}]
    user_words = 0

    console.print(
        Panel(
            f"[bold]session {session_id}[/] — talk to me. type [cyan]/quit[/] to wrap up.",
            border_style="blue",
        )
    )
    console.print()

    try:
        while True:
            try:
                line = console.input("[bold cyan]you>[/] ")
            except (EOFError, KeyboardInterrupt):
                line = "/quit"

            line = line.strip()
            if not line:
                continue
            if line in ("/quit", "/exit", "quit"):
                break

            user_words += _count_words(line)
            history.append({"role": "user", "content": line})

            reply_parts: list[str] = []
            live = Live(
                Markdown("_…_"),
                console=console,
                refresh_per_second=15,
                vertical_overflow="visible",
            )
            live.start()
            try:
                for chunk in llm.chat_stream(history):
                    reply_parts.append(chunk)
                    live.update(Markdown("".join(reply_parts)))
            except LLMError as exc:
                live.stop()
                console.print(f"\n[red]robbie:[/] {exc}")
                return 1
            live.stop()
            if not reply_parts:
                console.print("[dim]robbie: (no reply)[/]")
            history.append({"role": "assistant", "content": "".join(reply_parts)})
            console.print()

        return _wrap_up(coach, db, history, session_id, user_words)
    finally:
        llm.close()
        db.close()


def _wrap_up(coach: Coach, db: RobbieDB, history: list[dict], session_id: str, user_words: int) -> int:
    console.print("[italic]wrapping up…[/]")
    try:
        data = coach.wrap_up(history, session_id, date.today().isoformat())
    except (CoachError, LLMError) as exc:
        console.print(f"[red]robbie:[/] {exc}")
        return 1

    data["word_count"] = user_words
    session_file = SESSIONS_DIR / f"{session_id}.json"
    session_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    session = parse_session_file(session_file)
    db.upsert_session(session)
    try:
        summary = db.sync_rules(RULES_FILE)
        orphans = summary["orphan_rule_ids"]
    except RulesError:
        orphans = []

    append_session_log(
        f"## {session.date} — session {session_id}\n"
        f"**Topics:** {', '.join(session.topics) if session.topics else '(none)'}\n"
        f"**Words:** {session.word_count}\n"
        f"**Errors:** {len(session.errors)}\n"
        f"**Rating:** {session.rating():.1f}/10"
    )

    print(f"\nsaved {session_file}")
    console.print(
        f"[bold]rating[/] {session.rating():.1f}/10, {len(session.errors)} errors, "
        f"{session.word_count} words, "
        f"{session.errors_per_100_words() or 0:.2f} errors/100 words"
    )
    if orphans:
        console.print(
            f"[yellow]note:[/] new rule_ids without a catalog entry: {', '.join(orphans)}\n"
            f"add them to robbie_brain/common_mistakes.md, then run `robbie rules`"
        )
    return 0


def _count_words(text: str) -> int:
    return len(text.split())
