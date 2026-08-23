"""`robbie review` — spaced-repetition review of your vocab-gap cards.

Shows due cards (front = the L1 trigger word), lets you self-test, then grades
each card Again/Hard/Good/Easy. The grade advances the card's SM-2 state
(robbie/sm2.py) through the cards collection.
"""

from datetime import date

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .activate import _connect_db

console = Console()

GRADE_KEYS = {"a": "again", "h": "hard", "g": "good", "e": "easy"}
GRADE_NUMS = {"1": "again", "2": "hard", "3": "good", "4": "easy"}

GRADE_PROMPT = r"grade: \[a]gain \[h]ard \[g]ood \[e]asy  (or 1-4), \[q]uit → "


def parse_grade(key: str) -> str | None:
    """Map a user key (a/h/g/e or 1-4) to a grade; None if unrecognized."""
    key = key.strip().lower()
    return GRADE_KEYS.get(key) or GRADE_NUMS.get(key)


def review() -> int:
    db = _connect_db()
    if db is None:
        return 1

    try:
        today = date.today().isoformat()
        cards = db.due_cards(today)
        if not cards:
            console.print("[dim]no vocab cards due today — you're caught up[/]")
            return 0

        console.print(
            Panel(
                f"[bold]{len(cards)}[/] card(s) due. see the [cyan]front[/], answer "
                "out loud or in your head, then reveal the [cyan]back[/].",
                border_style="blue",
            )
        )

        reviewed = 0
        for card in cards:
            if not _review_one(db, card, today):
                break
            reviewed += 1

        console.print(f"\n[bold]done[/] — reviewed {reviewed} of {len(cards)} due card(s)")
        next_due = db.cards.count_documents(
            {"due_date": {"$lte": today}, "suspended": False}
        )
        if next_due:
            console.print(f"[dim]{next_due} card(s) still due — run `robbie review` again[/]")
        return 0
    finally:
        db.close()


def _review_one(db, card: dict, today: str) -> bool:
    slug = card["_id"]
    console.print()
    console.rule(f"[bold]{card['l1_word']}[/]", style="cyan")
    try:
        console.input("[dim]answer (any key to reveal)…[/] ")
    except (EOFError, KeyboardInterrupt):
        return False

    back = Table.grid(padding=(0, 1))
    back.add_column(style="bold green")
    back.add_column()
    back.add_row("→", card["target_word"])
    for ctx in card["contexts"]:
        back.add_row("·", f"[dim]{ctx['context']}[/]")
    console.print(back)
    console.print(
        f"[dim]{card['times_gapped']}x gapped · "
        f"{db.card_status(card)} · interval {card['interval_days']}d · "
        f"ease {card['ease_factor']:.2f}[/]"
    )

    while True:
        try:
            key = console.input(GRADE_PROMPT).strip().lower()
        except (EOFError, KeyboardInterrupt):
            key = "q"
        if key in ("q", "quit", ""):
            return False
        grade = parse_grade(key)
        if grade:
            db.review_card(slug, grade, today)
            return True
        console.print("[red]pick a, h, g, e (or 1-4)[/]")
