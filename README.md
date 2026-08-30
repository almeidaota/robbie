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
  record automatically. If PostgreSQL isn't running, it starts it via
  `docker compose up -d` for you.
- **Coach modes** — one mode per session, set at start with
  `robbie activate --mode formal`. `casual` always corrects; `formal` pushes a
  written/register-slip-aware workplace register; `interview` runs structured
  Q&A. The mode is saved with the session so ratings can be compared per mode.
- **Deterministic rating** — 0–10, recomputed from weights, never stored.
- **`errors_per_100_words`** — error density, from the word count counted by
  the app (not estimated).
- **PostgreSQL storage** — `sessions` + `errors` + `cards` tables.
  Facts in, verdicts out (the rating is never persisted).
- **Simpler alternative: SQLite** — don't want Docker? The [`simplified`]
  (https://github.com/almeidaota/robbie/tree/simplified) branch drops
  PostgreSQL entirely and stores everything in a single local `robbie.db`
  file via the stdlib `sqlite3` — zero setup, no Docker, no psycopg.
  Same features, same CLI. Check it out with
  `git checkout simplified`.
- **Spaced-repetition vocab cards** — every `(l1_word?)` gap in a session
  becomes a card (`cards` table), reviewed with your own SM-2 engine via
  `robbie review`, and exportable to Anki with `robbie export`.
- **Language-agnostic core** — a `language` field + per-language surface files
  (profile, session log) is all it takes to coach another L1→target pair.
- **Open source** — GPL-3.0, personal data gitignored, `*.example.md` templates
  shipped, all credentials live in a gitignored `.env`.

## Requirements

- Python 3.11+
- Docker (for PostgreSQL via `docker compose` — see `docker-compose.yml`)
- An LLM API key (OpenAI-compatible: DeepSeek, OpenAI, OpenRouter, …)

> No Docker / want a zero-setup local install? Use the [`simplified`]
> (https://github.com/almeidaota/robbie/tree/simplified) branch — it replaces
> PostgreSQL with a single SQLite file and needs only Python + an API key.

## Como rodar

All credentials live in one `.env` file at the repo root (gitignored — never
commit it). Copy the example and fill it in:

```sh
cp .env.example .env
```

Then edit `.env`. Every variable:

| Variable | Required | Default | Used by | Description |
|---|---|---|---|---|
| `LLM_API_KEY` | **yes** | — | `robbie/config.py` | Your LLM API key. Without it `robbie` won't start. |
| `LLM_BASE_URL` | no | `https://api.deepseek.com` | `robbie/config.py` | OpenAI-compatible API base URL. |
| `LLM_MODEL` | no | `deepseek-v4-flash` | `robbie/config.py` | Model to chat with. |
| `POSTGRES_HOST` | no | `localhost` | `robbie/db.py`, `docker-compose.yml` | Where PostgreSQL listens. |
| `POSTGRES_PORT` | no | `5432` | `robbie/db.py`, `docker-compose.yml` | PostgreSQL port. |
| `POSTGRES_USER` | no | `robbie` | `robbie/db.py`, `docker-compose.yml` | PostgreSQL user. |
| `POSTGRES_PASSWORD` | no | `robbie` | `robbie/db.py`, `docker-compose.yml` | PostgreSQL password. |
| `POSTGRES_DB` | no | `robbie` | `robbie/db.py`, `docker-compose.yml` | Database name. |

> **Note:** the `POSTGRES_*` values are read both by the app (`robbie/db.py`)
> and by `docker-compose.yml`, so the container and the app always agree.
> `MONGO_URI` (commented out in `.env.example`) was only used by the one-shot
> Mongo→Postgres migration script, which has been removed.

Setup, step by step:

```sh
# 1. Get the code
git clone <this-repo> && cd Robbie

# 2. Install the CLI (pipx keeps it isolated and puts `robbie` on your PATH)
pipx install -e .

# 3. Copy and fill the env file
cp .env.example .env
#   edit .env: put your LLM_API_KEY and, if you changed them, the POSTGRES_* values

# 4. Start PostgreSQL + the web admin (Adminer)
docker compose up -d
# browser UI: http://localhost:8081  (system=PostgreSQL, server=postgres,
#             user/pass/db = your POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB)

# 5. Point the CLI at your LLM (writes/updates .env interactively)
robbie setup
```

Or skip `robbie setup` and just set `LLM_API_KEY` in `.env` by hand.

Then create your personal files from the templates:

```sh
cp robbie_brain/profile.example.md          robbie_brain/profile.md
```

These are gitignored — the repo ships code, not your data.

## Usage

```sh
robbie activate                 # start a coaching session (casual mode)
robbie activate --mode formal   # one mode for the whole session
robbie show                     # dashboard: sessions, mode, ratings, errors per 100 words
robbie review       # spaced-repetition review of your vocab-gap cards
robbie export       # build an Anki .apkg from the vocab cards
```

### `robbie activate`

- Type normally; `robbie` replies in styled markdown and corrects your grammar
  as you go.
- A Portuguese word in parentheses with a `?` — e.g. `(atualize?)` — is treated
  as a vocab gap: the coach teaches the English word and moves on.
- **Modes** — one per session, chosen at start: `robbie activate --mode casual`
  (default, always corrects), `--mode formal` (workplace register + register
  slips), `--mode interview` (structured Q&A). The mode is stored on the
  session and shown in `robbie show`.
- **End the session** with `/quit`, or just say it ("let's wrap up", "I'm
  done") — the coach signals the wrap-up itself.
- On wrap-up, the coach emits the session record as JSON per the schema,
  validated by the parser (with up to 3 retries on schema errors). The app:
  - counts your words and stores the session + errors in PostgreSQL
  - prints the rating and errors/100 words

### `robbie review`

- Shows every vocab-gap card that's due today (front = the Portuguese trigger
  word, back = the English word + the contexts where you gapped).
- Self-test, then grade each card **Again / Hard / Good / Easy** — that drives
  the SM-2 spaced-repetition schedule stored on the card.
- New cards are due immediately; intervals grow by `interval × ease_factor`.

### `robbie export`

- Builds an Anki package (`robbie_vocab.apkg` by default) from every vocab
  card, offline via `genanki` — no Anki needed. One note per card: front = the
  L1 trigger word, back = the English word + every context sentence, in the
  `Robbie::English` deck. Suspended cards are skipped. One-way: exporting never
  touches the cards table.

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
  with the current weights (`robbie/parser.py`). Change `WEIGHTS` and every
  past session re-scores consistently on the next read.

**Example:** 5 transfers (5×0.6) + 1 grammar (1.0) + 1 self-caught transfer
(0.3) + 1 typo (0.3) = penalty 4.6 → **rating 5.4**.

**`errors_per_100_words`** = `errors ÷ words × 100`. Words are counted by the
app as you type, so the density metric is a fact, not a guess.

## Project layout

```
robbie/
  cli.py       # robbie command (activate, setup, show, review, export)
  activate.py  # interactive chat loop + wrap-up pipeline
  coach.py     # prompt assembly (profile, recent sessions) + wrap-up
  config.py    # credentials from .env (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL)
  llm.py       # OpenAI-compatible streaming client
  parser.py    # session schema + deterministic rating/counts
  sm2.py       # SM-2 spaced-repetition engine (pure, deterministic)
  review.py    # robbie review: grade due vocab cards
  export.py    # robbie export: build an Anki .apkg (genanki)
  db.py        # PostgreSQL: sessions, errors, cards
robbie_brain/  # your personal coach memory (gitignored) + *.example.md
               # agents/ holds the per-mode coach behavior (casual/formal/interview)
tests/         # unittest suite
```

## Storage model

PostgreSQL stores **facts, never verdicts**:

- `sessions` — one row per session (meta, topics, notes, word count,
  vocab gaps as JSONB), keyed by `session_id`.
- `errors` — one row per error (type, quote, fix, self_caught), referencing
  `session_id` (a `SERIAL id` keeps insertion order).
- `cards` — one row per `(l1_word, target_word)` vocab-gap pair: the facts
  (`contexts` as JSONB, `first_seen`, `last_seen`, `times_gapped`) plus the
  mutable SM-2 review state (`repetitions`, `ease_factor`, `interval_days`,
  `due_date`, `last_reviewed`). Keyed by a stable slug like
  `substituir->replace`.

`robbie show` is the live dashboard: "how many preposition errors ever?" is a
group-by query, not a hand-edited counter.

## Development

```sh
pip install -e .
python -m unittest discover -s tests   # run the suite (needs PostgreSQL up)
```

## License

GPL-3.0 — see [LICENSE](LICENSE).
