import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from robbie.export import _contexts_html, build_deck, export


def card(slug, l1, target, contexts, suspended=False):
    return {
        "slug": slug,
        "l1_word": l1,
        "target_word": target,
        "contexts": [{"session_id": "s", "date": "d", "context": c} for c in contexts],
        "suspended": suspended,
    }


class TestBuildDeck(unittest.TestCase):
    def test_one_note_per_card(self):
        deck = build_deck([
            card("a->b", "a", "b", ["i saw (a?)"]),
            card("c->d", "c", "d", ["x (c?) y"]),
        ])
        self.assertEqual(len(deck.notes), 2)
        note = deck.notes[0]
        self.assertEqual(note.fields, ["a", "b", "i saw (a?)"])
        self.assertIn("robbie", note.tags)

    def test_skips_suspended(self):
        deck = build_deck([
            card("a->b", "a", "b", [], suspended=True),
            card("c->d", "c", "d", []),
        ])
        self.assertEqual(len(deck.notes), 1)
        self.assertEqual(deck.notes[0].fields[0], "c")

    def test_empty_cards(self):
        self.assertEqual(len(build_deck([]).notes), 0)


class TestContextsHtml(unittest.TestCase):
    def test_joins_with_breaks(self):
        c = card("a->b", "a", "b", ["one (a?)", "two (a?)"])
        self.assertEqual(_contexts_html(c), "one (a?)<br>two (a?)")

    def test_drops_empty(self):
        c = card("a->b", "a", "b", ["one (a?)", ""])
        self.assertEqual(_contexts_html(c), "one (a?)")

    def test_escapes_html(self):
        c = card("a->b", "a", "b", ["a < b & c > d"])
        self.assertEqual(_contexts_html(c), "a &lt; b &amp; c &gt; d")


class TestExport(unittest.TestCase):
    def test_writes_valid_apkg_zip(self):
        with TemporaryDirectory() as tmp:
            deck = build_deck([card("a->b", "a", "b", ["i saw (a?)"])])
            out = export(deck, Path(tmp) / "deck.apkg")
            self.assertTrue(out.exists())
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
                self.assertIn("collection.anki2", names)


if __name__ == "__main__":
    unittest.main()
