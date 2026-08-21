# Robbie

A deterministic English coach that lives in your terminal.

You chat with it like a friend; it corrects your grammar, tracks the errors
over time, and scores each session. The part that **recognizes** errors is an
LLM (fuzzy, human-grade judgment). Everything after that — parsing, rating,
counters, storage — is **deterministic code**: the same session always yields
the same numbers, and past sessions re-score consistently if you ever tune the
weights.

```
Recognition (LLM, fuzzy)  →  session facts (JSON)  →  scoring (deterministic)
```

## Features

- **`robbie activate`** — an interactive coaching chat. Streams styled replies,
  counts the words you write, and on wrap-up produces a facts-only session
  record automatically.
- **Deterministic rating** — 0–10, recomputed from weights, never stored.
- **`errors_per_100_words`** — error density, from the word count counted by
  the app (not estimated).
- **Rules catalog** — `common_mistakes.md` is the single source of truth for
  the rules; synced into MongoDB and referenced by every error.
- **MongoDB storage** — `sessions` + `errors` + `rules` collections. Facts in,
  verdicts out (the rating is never persisted).
- **Language-agnostic core** — a `language` field + per-language surface files
  (profile, rules, session log) is all it takes to coach another L1→target pair.
- **Open source** — GPL-3.0, personal data gitignored, `*.example.md` templates
  shipped, keys via env var / config file.

## Requirements

- Python 3.11+
- MongoDB (via `docker compose` — see `docker-compose.yml`)
- An LLM API key (OpenAI-compatible: DeepSeek, OpenAI, OpenRouter, …)

## Setup

```sh
# 1. Get the code
git clone <this-repo> && cd Robbie

# 2. Install the CLI (pipx keeps it isolated and puts `robbie` on your PATH)
pipx install -e .

# 3. Start MongoDB + the web admin (mongo-express)
docker compose up -d
# browser UI: http://localhost:8081  (admin / pass)

# 4. Point the CLI at your LLM
robbie setup          # asks for key, base URL, and model (picklist)
#   ~/.config/robbie/config.toml   (chmod 600, never in the repo)
#   env vars LLM_API_KEY / LLM_BASE_URL / LLM_MODEL override the file
```

Then create your personal files from the templates:

```sh
cp robbie_brain/profile.example.md          robbie_brain/profile.md
cp robbie_brain/common_mistakes.example.md  robbie_brain/common_mistakes.md
cp robbie_brain/session_log.example.md      robbie_brain/session_log.md
```

These are gitignored — the repo ships code, not your data.

## Usage

```sh
robbie activate     # start a coaching session
robbie show         # dashboard: sessions, ratings, errors per 100 words
robbie load         # (re)load session JSON files into MongoDB
robbie rules        # sync common_mistakes.md into the rules collection
```

### `robbie activate`

- Type normally; `robbie` replies in styled markdown and watches for the
  errors from your rules catalog.
- A Portuguese word in parentheses with a `?` — e.g. `(atualize?)` — is treated
  as a vocab gap: the coach teaches the English word and moves on.
- **End the session** with `/quit`, or just say it ("let's wrap up", "I'm
  done") — the coach signals the wrap-up itself.
- On wrap-up, the coach emits the session record as JSON per the schema,
  validated by the parser (with up to 3 retries on schema errors). The app:
  - writes `sessions/<session_id>.json`
  - counts your words and stores the session + errors in MongoDB
  - appends a summary to `robbie_brain/session_log.md`
  - prints the rating and errors/100 words
  - warns about any new `rule_id`s that don't exist in the catalog yet

## The rating, explained

```
rating = clamp(10 − Σ penalties, 0, 10)
```

| Error type | Weight | Meaning |
|---|---|---|
| `grammar`  | 1.0 | wrong structure |
| `transfer` | 0.6 | L1 interference (e.g. Portuguese → English) |
| `typo`     | 0.3 | spelling / slip |
| `style`    | 0.0 | valid but unnatural — never docks |

- A **self-caught** error (you corrected yourself mid-conversation) halves its
  weight.
- The rating is **never stored** — it's recomputed from the session's facts
  with the current weights (`robbie/parser.py`). Change `WEIGHTS` and re-run
  `robbie load`; every past session re-scores consistently.

**Example:** 5 transfers (5×0.6) + 1 grammar (1.0) + 1 self-caught transfer
(0.3) + 1 typo (0.3) = penalty 4.6 → **rating 5.4**.

**`errors_per_100_words`** = `errors ÷ words × 100`. Words are counted by the
app as you type, so the density metric is a fact, not a guess.

## Project layout

```
robbie/
  cli.py       # robbie command (activate, setup, show, load, rules)
  activate.py  # interactive chat loop + wrap-up pipeline
  coach.py     # prompt assembly (profile, rules, recent sessions) + wrap-up
  config.py    # ~/.config/robbie/config.toml + env overrides
  llm.py       # OpenAI-compatible streaming client
  parser.py    # session schema + deterministic rating/counts
  rules.py     # common_mistakes.md → rules collection
  db.py        # MongoDB: sessions, errors, rules
robbie_brain/  # your personal coach memory (gitignored) + *.example.md
sessions/      # session JSON records (gitignored)
tests/         # unittest suite
```

## Storage model

MongoDB stores **facts, never verdicts**:

- `sessions` — one document per session (meta, topics, notes, word count,
  vocab gaps), keyed by `session_id`.
- `errors` — one document per error, referencing `session_id` + `rule_id`.
- `rules` — the catalog synced from `common_mistakes.md`.

`robbie show` is the live dashboard: "how many preposition errors ever?" is a
group-by query, not a hand-edited counter.

## Development

```sh
python -m unittest discover -s tests   # run the suite
```

## License

GPL-3.0 — see [LICENSE](LICENSE).
