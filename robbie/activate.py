"""`robbie activate` — the interactive coach session.

Chat loop: reads user input, streams coach replies, counts the user's words
as they type. On /quit, asks the coach for the session JSON, validates it
against the schema, stores it, and appends a human summary to session_log.md.
"""

import subprocess
import sys
import time
from datetime import date

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from .coach import Coach, CoachError, append_session_log
from .config import ConfigError, load_config
from .db import DBError, RobbieDB
from .llm import LLMClient, LLMError
from .parser import DEFAULT_MODE, parse_session

console = Console()


def next_session_id(db: RobbieDB) -> str:
    """date + counter, e.g. 2026-08-21-03 (deterministic per stored sessions)."""
    today = date.today().isoformat()
    counts = []
    for sid in db.session_ids_on(today):
        if sid.startswith(today):
            try:
                counts.append(int(sid.rsplit("-", 1)[1]))
            except ValueError:
                continue
    return f"{today}-{max(counts, default=0) + 1:02d}"


def _compose_up() -> bool:
    """Start PostgreSQL (+ Adminer) via docker compose. True on success."""
    console.print("[dim]starting PostgreSQL via docker compose…[/]")
    try:
        proc = subprocess.run(
            ["docker", "compose", "up", "-d"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        console.print("[red]robbie:[/] docker not found on PATH")
        return False
    if proc.returncode != 0:
        console.print(f"[red]robbie:[/] `docker compose up -d` failed:\n{proc.stdout}{proc.stderr}")
        return False
    return True


def _connect_db(max_retries: int = 5, delay: float = 1.0) -> RobbieDB | None:
    """Connect to PostgreSQL, starting docker compose on demand if needed."""
    try:
        return RobbieDB()
    except DBError as exc:
        console.print(f"[yellow]robbie:[/] {exc}")
        if not _compose_up():
            console.print("is the database up? try: docker compose up -d")
            return None
        for attempt in range(1, max_retries + 1):
            try:
                return RobbieDB()
            except DBError:
                if attempt < max_retries:
                    time.sleep(delay)
        console.print("[red]robbie:[/] PostgreSQL still not reachable after `docker compose up -d`")
        return None


def activate(mode: str = DEFAULT_MODE) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        console.print(f"[red]robbie:[/] {exc}")
        return 1

    db = _connect_db()
    if db is None:
        return 1

    llm = LLMClient(config)
    coach = Coach(llm, db, mode=mode)
    session_id = next_session_id(db)

    history: list[dict] = [{"role": "system", "content": coach.system_prompt()}]
    user_words = 0

    console.print(
        Panel(
            f"[bold]session {session_id}[/] — mode [cyan]{coach.mode}[/]. "
            f"talk to me. type [cyan]/quit[/] to wrap up.",
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
            want_wrap_up = False

            def render():
                text = _strip_wrap_marker("".join(reply_parts)) or "_…_"
                return Markdown(f"**robbie>** {text}")

            live = Live(
                render(),
                console=console,
                refresh_per_second=15,
                vertical_overflow="visible",
            )
            live.start()
            try:
                for chunk in llm.chat_stream(history):
                    reply_parts.append(chunk)
                    live.update(render())
                    if _has_wrap_marker("".join(reply_parts)):
                        want_wrap_up = True
                        break
            except LLMError as exc:
                live.stop()
                console.print(f"\n[red]robbie:[/] {exc}")
                return 1
            reply = _strip_wrap_marker("".join(reply_parts)).strip()
            live.update(Markdown(f"**robbie>** {reply or '_…_'}"))
            live.stop()
            if not reply:
                console.print("[dim]robbie> (no reply)[/]")
            if reply:
                history.append({"role": "assistant", "content": reply})
            console.print()
            if want_wrap_up:
                break

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
    data["mode"] = coach.mode
    session = parse_session(data)

    db.upsert_session(session)
    n_cards = db.sync_cards_from_session(session)

    append_session_log(
        f"## {session.date} — session {session_id}\n"
        f"**Topics:** {', '.join(session.topics) if session.topics else '(none)'}\n"
        f"**Words:** {session.word_count}\n"
        f"**Errors:** {len(session.errors)}\n"
        f"**Rating:** {session.rating():.1f}/10"
    )

    console.print(
        f"[bold]rating[/] {session.rating():.1f}/10, {len(session.errors)} errors, "
        f"{session.word_count} words, "
        f"{session.errors_per_100_words() or 0:.2f} errors/100 words"
    )
    _show_session_facts(session)
    if n_cards:
        console.print(f"[cyan]vocab cards:[/] {n_cards} gapped pair(s) upserted — try `robbie review`")
    return 0


def _show_session_facts(session) -> None:
    """Print the session's errors and vocab gaps right after wrap-up."""
    if session.errors:
        console.print("\n[bold]errors:[/]")
        for e in session.errors:
            self_caught = " (self-caught)" if e.self_caught else ""
            console.print(
                f"  [yellow]{e.quote} → [green]{e.fix}[/] "
                f"({e.type}{self_caught})"
            )
    if session.vocab_gaps:
        console.print("\n[bold]vocab gaps:[/]")
        for g in session.vocab_gaps:
            console.print(f"  [cyan]{g.l1_word}[/] → {g.target_word}  [dim]{g.context}[/]")


def _count_words(text: str) -> int:
    return len(text.split())


WRAP_MARKER = "<wrap_up>"


def _has_wrap_marker(text: str) -> bool:
    return WRAP_MARKER in text


def _strip_wrap_marker(text: str) -> str:
    return text.replace(WRAP_MARKER, "")
