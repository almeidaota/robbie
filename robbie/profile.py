"""First-run onboarding: ask the learner a few questions and write profile.md.

On the first `robbie activate`, before the session starts, the learner answers
a short questionnaire. The answers are written to robbie_brain/profile.md (in
the same shape as profile.example.md), which the coach injects into every
session. Later runs skip the questionnaire because the file already exists.
"""

from pathlib import Path

from rich.console import Console

from .coach import PROFILE_FILE

console = Console()

QUESTIONS = [
    ("Name / nickname", ""),
    ("Level", "upper-intermediate"),
    ("Why you're practicing", ""),
    ("Interests & life context", ""),
    ("Things the coach should never forget", ""),
    ("Preferences", "casual tone, no over-praise, correct me inline but stay chill"),
]

DEFAULTS = {label: default for label, default in QUESTIONS}

FIXED_FIELDS = [
    ("Native language", "Portuguese"),
    ("Target language", "English"),
]


def ensure_profile(path: Path = PROFILE_FILE, *, answers: list[str] | None = None) -> bool:
    """Ask the onboarding questions and write profile.md if it's missing.

    Returns True when the profile was created, False when it already existed.
    """
    if path.exists():
        return False

    replies = answers if answers is not None else []
    values: dict[str, str] = {}
    console.print("[bold]first run![/] a few quick questions so I know who I'm coaching:")
    for label, default in QUESTIONS:
        if replies:
            value = (replies.pop(0) or default).strip()
        else:
            hint = f" [{default}]" if default else ""
            try:
                value = (console.input(f"{label}{hint}: ").strip() or default).strip()
            except EOFError:
                value = default
        values[label] = value

    _write_profile(path, values)
    console.print(f"[green]profile saved:[/] {path}")
    return True


def _write_profile(path: Path, values: dict[str, str]) -> None:
    """Write profile.md in the shape of profile.example.md."""
    lines = [
        "# Learner Profile",
        "",
        "Filled in on first run of `robbie activate`. Edit this file freely —",
        "it's injected into every session so the coach remembers who you are.",
        "",
    ]
    for label, default in FIXED_FIELDS:
        lines.append(f"- **{label}:** {default}")
    for label, _ in QUESTIONS:
        lines.append(f"- **{label}:** {values.get(label, '')}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
