"""`robbie activate` — the interactive coach session.

Chat loop: reads user input, streams coach replies, counts the user's words
as they type. On /quit, asks the coach for the session JSON, validates it
against the schema, stores it, and appends a human summary to session_log.md.
"""

import sys
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
from .profile import PROFILE_FILE, apply_updates, ensure_profile

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


def _connect_db() -> RobbieDB | None:
    """Open the local SQLite database. Returns None on failure."""
    try:
        return RobbieDB()
    except DBError as exc:
        console.print(f"[red]robbie:[/] {exc}")
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

    ensure_profile()

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
    if session.profile_updates:
        _offer_profile_updates(session.profile_updates)
    if n_cards:
        console.print(f"[cyan]vocab cards:[/] {n_cards} gapped pair(s) upserted — try `robbie review`")
    return 0


def _offer_profile_updates(updates) -> None:
    """Show the coach's suggested profile changes and ask before applying."""
    console.print("\n[bold]coach noticed something new about you:[/]")
    for update in updates:
        console.print(f"  [cyan]{update.field}:[/] {update.value}")
    try:
        answer = console.input("  update profile? [y/N]: ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        console.print("[dim]profile left unchanged[/]")
        return
    applied = apply_updates(PROFILE_FILE, [(u.field, u.value) for u in updates])
    if applied:
        console.print(f"[green]profile updated:[/] {', '.join(applied)}")
    else:
        console.print("[dim]profile unchanged (nothing new)[/]")


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
