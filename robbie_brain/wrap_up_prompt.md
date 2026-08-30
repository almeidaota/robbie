The session is over. Write the session record as a single JSON object, no
other text, no markdown fences. Follow this schema exactly:

{
  "schema_version": 1,
  "session_id": "{session_id}",
  "date": "{date}",
  "topics": ["short topic", "..."],
  "notes": "one or two sentences about the session",
  "errors": [
    {
      "type": "grammar|transfer|typo|style",
      "quote": "what I actually wrote",
      "fix": "the corrected version",
      "self_caught": false
    }
  ],
  "vocab_gaps": [
    {"l1_word": "palavra", "target_word": "word", "context": "I need to (palavra?) that line"}
  ]
}

Rules:
- ONLY include errors that actually happened in this session.
- type: grammar = wrong structure; transfer = Portuguese interference;
  typo = spelling/slip; style = valid but unnatural.
- self_caught: true only if I corrected myself mid-conversation.
- For every vocab_gap, context MUST be the full sentence I actually typed,
  with the L1 word in parentheses where I flagged it. Never just "(word)"
  on its own — the sentence is what makes the gap learnable.
