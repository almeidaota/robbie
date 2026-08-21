"""Parse the rules catalog (common_mistakes.md) into structured Rule docs.

The catalog is the single source of truth for rule definitions. The errors
collection stores *occurrences*; this module defines what a rule *is*.

Sections:
  ## Active Errors   - numbered rules, each a Rule doc
  ## Style Preferences - one rule doc (rule_id "style") whose examples are the bullets
  ## Cleared         - one rule doc (rule_id "cleared")

Parsing is deterministic: same file always yields the same rules.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

SECTION_ACTIVE = "active"
SECTION_STYLE = "style"
SECTION_CLEARED = "cleared"

_RULE_RE = re.compile(r"^###\s+(\d+)\.\s+(.+)$")
_BULLET_RE = re.compile(r"^-\s+\*\*(.+?):\*\*\s*(.*)$")


@dataclass
class Rule:
    rule_id: str
    title: str
    section: str
    wrong: str = ""
    right: str = ""
    times_repeated: int | None = None
    notes: str = ""
    examples: list[dict[str, str]] = field(default_factory=list)

    def to_doc(self, source: str = "") -> dict:
        return {
            "_id": self.rule_id,
            "rule_id": self.rule_id,
            "title": self.title,
            "section": self.section,
            "wrong": self.wrong,
            "right": self.right,
            "times_repeated": self.times_repeated,
            "notes": self.notes,
            "examples": self.examples,
            "source": source,
        }


class RulesError(ValueError):
    """Raised when the catalog file can't be parsed."""


def parse_rules_file(path: str | Path) -> list[Rule]:
    path = Path(path)
    if not path.exists():
        raise RulesError(f"rules catalog not found: {path}")
    return parse_rules(path.read_text(encoding="utf-8"), source=str(path))


def parse_rules(text: str, source: str = "") -> list[Rule]:
    section = SECTION_ACTIVE
    current: Rule | None = None
    rules: list[Rule] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            if heading.startswith("style"):
                section = SECTION_STYLE
            elif heading.startswith("cleared"):
                section = SECTION_CLEARED
            else:
                section = SECTION_ACTIVE
            current = None
            continue

        if section == SECTION_STYLE:
            m = _BULLET_RE.match(stripped)
            if m:
                key, value = m.group(1), m.group(2).strip()
                if current is None:
                    current = Rule(rule_id="style", title="Style Preferences", section=SECTION_STYLE)
                    rules.append(current)
                _apply_bullet(current, key, value)
            elif stripped.startswith("- "):
                if current is None:
                    current = Rule(rule_id="style", title="Style Preferences", section=SECTION_STYLE)
                    rules.append(current)
                current.examples.append(_split_arrow(stripped[2:]))
            continue

        m = _RULE_RE.match(stripped)
        if m:
            current = Rule(rule_id=m.group(1), title=m.group(2), section=section)
            rules.append(current)
            continue

        if section == SECTION_CLEARED:
            if current is None:
                current = Rule(rule_id="cleared", title="Cleared", section=SECTION_CLEARED)
                rules.append(current)
            current.notes = stripped.lstrip("- ").strip()
            continue

        if current is None:
            continue

        if stripped.startswith("- "):
            bullet = _BULLET_RE.match(stripped)
            if bullet:
                _apply_bullet(current, bullet.group(1), bullet.group(2).strip())

    return rules


def _apply_bullet(rule: Rule, key: str, value: str) -> None:
    if key == "Wrong":
        rule.wrong = value
    elif key == "Right":
        rule.right = value
    elif key == "Times repeated":
        try:
            rule.times_repeated = int(value.split()[0])
        except (ValueError, IndexError):
            rule.times_repeated = None
    elif key == "Notes":
        rule.notes = value


def _split_arrow(example: str) -> dict[str, str]:
    """Split a style bullet like "a" -> "b" into {wrong, right}."""
    parts = example.split("→", 1)
    if len(parts) == 2:
        return {"wrong": parts[0].strip().strip('"'), "right": parts[1].strip().strip('"')}
    return {"wrong": example, "right": ""}
