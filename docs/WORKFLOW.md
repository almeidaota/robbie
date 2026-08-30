# Robbie workflow

How the pieces call each other, from `robbie` on the command line to the
PostgreSQL tables. The core loop is `activate`; the rest are small utilities
that read or sync the same data.

## Entry point and bootstrap

Every command starts the same way:

```
robbie <cmd>
  └─ robbie.cli:main()                       cli.py:149   (entry point: pyproject.toml [project.scripts])
       └─ argparse → args.func(args)
            ├─ cmd_activate → activate()     cli.py:26 / activate.py:82
            ├─ cmd_setup    → write_config() cli.py:69
            ├─ cmd_show     → db reads       cli.py:104
            ├─ cmd_review   → review()       cli.py:132 / review.py:30
            └─ cmd_export   → build_deck     cli.py:136
```

Errors bubble to `main()`, which prints them as `robbie: <err>` and returns 1:
it catches `DBError` and `ConfigError` (cli.py:195).

### What happens at import time

`robbie/coach.py` resolves paths once, from `__file__`, so it works no matter
where you run it:

```
ROOT_DIR    = repo root                coach.py:16
BRAIN_DIR   = ROOT_DIR / "robbie_brain"
AGENTS_FILE       → AGENTS.md
MODE_AGENTS_DIR   → agents/<mode>.md     (casual / formal / interview)
PROFILE_FILE      → profile.md
WRAP_UP_PROMPT_FILE → wrap_up_prompt.md
```

`robbie/config.py` resolves the config path once:
`~/.config/robbie/config.toml` (or `$XDG_CONFIG_HOME/robbie/config.toml`).

## `robbie activate` — the main workflow

```
activate(mode)                              activate.py:82
  1. load_config()                          config.py:36   defaults → config.toml → env vars
  2. _connect_db()                          activate.py:63 RobbieDB() ping; on fail: docker compose up, retry 5×
  3. LLMClient(config)                      llm.py:19      OpenAI-compatible httpx client
  4. Coach(llm, db, mode=mode)              coach.py:32    validates mode ∈ {casual, formal, interview}
  5. next_session_id(db)                    activate.py:31 YYYY-MM-DD-NN from the sessions table
  6. history = [system: coach.system_prompt()]  activate.py:97
     └─ loop → _wrap_up()                  activate.py:161/167
```

### Step 2 — database connection

`RobbieDB.__init__` (db.py:40) connects to PostgreSQL with a 3s timeout (DSN
from the `.env`) and creates the tables + indexes if missing: `sessions`,
`errors`, `cards` (`errors.session_id`, `cards.due_date`). If the connect
fails, `_connect_db` auto-runs `docker compose up -d` (`_compose_up`,
activate.py:45) and retries 5 times at 1s intervals.

### Step 6 — the system prompt

`coach.system_prompt()` (coach.py:47) assembles the prompt deterministically
from the brain files, joining sections with blank lines:

```
parts =
  AGENTS.md                         role + correction protocol + wrap-up contract
  "## Active mode: <mode>" + agents/<mode>.md   per-mode behavior
  "## Learner profile"  + profile.md
  "## Last sessions"    + _recent_sessions()    (last 2 sessions, with rating)
  fixed closing paragraph: casual tone + the <wrap_up> marker contract
```

Missing files are skipped (`_read_or` returns `""`).

### The chat loop (activate.py:110)

```
while True:
  line = console.input("you> ")                     EOF/Ctrl-C → "/quit"
  /quit / /exit / quit → break
  user_words += _count_words(line)                  activate.py:230
  history += {"role":"user", content: line}
  for chunk in llm.chat_stream(history):            llm.py:56
      render via rich Live
      if _has_wrap_marker(chunks): break            marker = "<wrap_up>" activate.py:234
  history += {"role":"assistant", content: reply-stripped-of-marker}
  LLMError → return 1
```

The coach decides when the session is over: it appends `<wrap_up>` to its own
reply (per AGENTS.md), and the app stops streaming the moment the marker shows
up, then strips it.

### Wrap-up — `_wrap_up` (activate.py:167)

```
coach.wrap_up(history, session_id, date)      coach.py:103
   prompt = wrap_up_prompt.md with {session_id}/{date} replaced
   messages = system_prompt + history + prompt
   ≤3 attempts:
       llm.chat(messages, json_mode=True)     json_object response_format
       _extract_json(reply)                   coach.py:151  fenced or raw JSON
       parse_session(data)                    parser.py:121 schema validation
       on SchemaError/ValueError/JSONDecodeError:
           append "That session JSON failed validation: <err>. Reply again…" and retry
   all attempts fail → CoachError

data["word_count"] = user_words ; data["mode"] = coach.mode
parse_session(data) → Session                   parser.py:121 (no file round-trip)
db.upsert_session(session)                      db.py:51     replace session + its errors
db.sync_cards_from_session(session)             db.py:128    vocab gaps → cards
print rating, errors/100 words, session facts, new card count
```

The wrap-up JSON is the only LLM-produced thing that touches storage, and it
must pass `parse_session` before it's stored — recognition is fuzzy, storage is
not. The `sessions` table is the source of truth; no session file is kept.

## The deterministic backend

- `Session.rating()` (parser.py:77): `clamp(10 − Σ penalties, 0, 10)`, computed
  from the `WEIGHTS` table (parser.py:22), halving self-caught errors. **Never
  stored** — recomputed on every read.
- `Session.errors_per_100_words()` (parser.py:82): from the word count the app
  tallied while you typed.
- `db.upsert_session` stores facts only (no rating); change `WEIGHTS` and every
  past session re-scores on the next read — no re-load needed.

## Other commands

| Command | What it does | Calls |
|---|---|---|
| `robbie show` | dashboard | `db.all_sessions()` → `rating()` + `errors_per_100_words()` per session; `counts_by_type()` GROUP BY query (db.py:126) |
| `robbie review` | spaced repetition | `_connect_db` → `db.due_cards(today)` → per card `_review_one`: reveal back, then `db.review_card(slug, grade, today)` (db.py:290) which runs `sm2.CardState.with_review` (sm2.py:40) and persists the new state |
| `robbie export [out]` | Anki package | `db.all_cards()` → `build_deck` (export.py:37, skips suspended) → `export` writes `.apkg` via genanki |
| `robbie setup` | LLM config | `write_config` (config.py:61) → repo-root `.env`, chmod 600 |

## Data flow

```
LLM recognition (fuzzy)
   │  <wrap_up> marker → wrap-up prompt
   ▼
session JSON  (validated by parser.py, ≤3 retries)
   │  db.upsert_session
   ▼
PostgreSQL (facts only)
   ├─ sessions  ──►  rating() recomputed from WEIGHTS on every read
   ├─ errors    ──►  counts_by_type (GROUP BY)
   └─ cards     ◄── sync_cards_from_session (vocab gaps)
        │  robbie review → SM-2 (sm2.py)
        ▼
   Anki .apkg (robbie export)
```

## Storage model

- `sessions` — one row per session (meta, topics, notes, word count, vocab
  gaps as JSONB), keyed by `session_id`. Facts, never verdicts.
- `errors` — one row per error (type, quote, fix, self_caught), referencing
  `session_id`; a `SERIAL id` keeps insertion order.
- `cards` — one row per `(l1_word, target_word)` pair, keyed by the stable slug
  `sm2.card_slug` (`atualize->update`): the facts (`contexts` as JSONB,
  `first_seen`, `last_seen`, `times_gapped`) plus the mutable SM-2 state
  (`repetitions`, `ease_factor`, `interval_days`, `due_date`, `last_reviewed`).
