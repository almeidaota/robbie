# Robbie

A deterministic English coach. You chat with it in your terminal; it
corrects you like a friend. All scoring is computed from facts, never
stored as vibes.

## How it works

- **Recognition stays fuzzy** — the coach (an LLM) spots your errors.
- **Everything after that is deterministic** — the coach emits a
  facts-only session file (errors, vocab gaps, topics, notes); the
  rating, counters, and metrics are computed by this code, every time.

## Setup

```sh
git clone <this-repo> && cd Robbie
pip install -e .
robbie setup            # asks for your LLM API key, writes ~/.config/robbie/config.toml
```

Your data lives in `robbie_brain/` (profile, rules, session log) and
`sessions/` — both gitignored. The repo ships `*.example.md` templates
so you can bootstrap.

## Use

```sh
robbie activate     # start a session; /quit to wrap up
robbie show         # dashboard: sessions, ratings, errors per 100 words
robbie load         # (re)load session files into the database
robbie rules        # sync the rules catalog into the database
```

## Storage

- Sessions and errors live in MongoDB (see `docker-compose.yml`).
- The database stores facts, never the rating. Change the weights in
  `robbie/parser.py` and every past session re-scores consistently.

## License

GPL-3.0 — see [LICENSE](LICENSE).
