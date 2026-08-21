import unittest

from robbie.rules import parse_rules, parse_rules_file

SAMPLE = """\
# Common Mistakes Tracker

## Active Errors

### 1. Dropping the subject "I"
- **Wrong:** "probably would run a little" / "but went one"
- **Right:** "I'd probably run a little" / "but I went once"
- **Times repeated:** 3
- **Notes:** Also happens in compound sentences.

### 2. Preposition mixups
- **Wrong:** "working at my phrases"
- **Right:** "working on my phrases"
- **Times repeated:** 10
- **Notes:** at = point, on = surface.

## Style Preferences (not wrong, just more natural)

- "have the fear that" → "I'm afraid that"
- "get things more serious" → "take things seriously"

## Cleared

- (none yet)
"""


class TestParseRules(unittest.TestCase):
    def test_parses_active_rules(self):
        rules = parse_rules(SAMPLE)
        numbered = [r for r in rules if r.section == "active"]
        self.assertEqual(len(numbered), 2)
        self.assertEqual(numbered[0].rule_id, "1")
        self.assertEqual(numbered[0].title, 'Dropping the subject "I"')
        self.assertEqual(numbered[0].times_repeated, 3)
        self.assertEqual(numbered[1].rule_id, "2")
        self.assertEqual(numbered[1].times_repeated, 10)

    def test_style_section_is_single_rule_with_examples(self):
        style = [r for r in parse_rules(SAMPLE) if r.section == "style"]
        self.assertEqual(len(style), 1)
        self.assertEqual(style[0].rule_id, "style")
        self.assertEqual(
            style[0].examples,
            [
                {"wrong": "have the fear that", "right": "I'm afraid that"},
                {"wrong": "get things more serious", "right": "take things seriously"},
            ],
        )

    def test_cleared_section(self):
        cleared = [r for r in parse_rules(SAMPLE) if r.section == "cleared"]
        self.assertEqual(len(cleared), 1)
        self.assertEqual(cleared[0].rule_id, "cleared")
        self.assertEqual(cleared[0].notes, "(none yet)")

    def test_round_works_on_real_file(self):
        from pathlib import Path

        rules = parse_rules_file(Path("robbie_brain/common_mistakes.md"))
        self.assertEqual(len(rules), 23)
        r2 = next(r for r in rules if r.rule_id == "2")
        self.assertEqual(r2.times_repeated, 10)
        self.assertTrue(r2.wrong.startswith('"working at my phrases"'))
        self.assertTrue(r2.right.startswith('"working on my phrases"'))


if __name__ == "__main__":
    unittest.main()
