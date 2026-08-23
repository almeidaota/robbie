"""`robbie export` — build an Anki .apkg from the cards collection.

One-way escape hatch to Anki (per project_brainstorm.md): one note per card,
front = l1_word, back = target_word + every context sentence, in a deck named
`Robbie::English`. genanki builds the package offline — Anki doesn't need to
be running.
"""

from pathlib import Path

import genanki

DECK_NAME = "Robbie::English"

# Fixed, arbitrary ids so re-exports stay stable and never collide.
DECK_ID = 1656252760001
MODEL_ID = 1656252760002

MODEL = genanki.Model(
    model_id=MODEL_ID,
    name="Robbie vocab card",
    fields=[
        {"name": "L1"},
        {"name": "Target"},
        {"name": "Contexts"},
    ],
    templates=[
        {
            "name": "Robbie card",
            "qfmt": "{{L1}}",
            "afmt": '{{FrontSide}}<hr id="answer">{{Target}}<br>{{Contexts}}',
        },
    ],
)


def build_deck(cards: list[dict]) -> genanki.Deck:
    """One note per card; suspended cards are left out."""
    deck = genanki.Deck(deck_id=DECK_ID, name=DECK_NAME)
    for card in cards:
        if card.get("suspended"):
            continue
        deck.add_note(
            genanki.Note(
                model=MODEL,
                fields=[
                    card["l1_word"],
                    card["target_word"],
                    _contexts_html(card),
                ],
                tags=["robbie"],
            )
        )
    return deck


def export(deck: genanki.Deck, output: str | Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    genanki.Package(deck).write_to_file(str(output))
    return output


def _contexts_html(card: dict) -> str:
    contexts = [c.get("context", "") for c in card.get("contexts", [])]
    return "<br>".join(_esc(c) for c in contexts if c)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
