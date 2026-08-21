# Brainstorm: Deterministic English Coach Project

Date: 2026-08-20
Status: Draft — still being drawn in my head

## The Core Problem

"It's a typo, it isn't!!!"

Classifying typos vs. actual grammar errors, and making the session tracking
consistent and fair. Right now the coach (AI) does all of it by vibes and
hand-edits the counters. Goal: make the parts that *can* be deterministic
actually be deterministic.

## The Plan (user's original)

- At the end of every session, write a **JSON or YAML file** with a preset structure.
- A **Python script** parses it, calculates the session **rating**, and saves the
  session log into a **non-relational database** (MongoDB — doubles as a NoSQL
  learning goal).
- Considered saving the whole raw conversation, but it'd get heavy fast —
  dropped.

## Coach's Feedback / Refinements

1. **Store facts, not verdicts.**
   - Don't hardcode the rating in the YAML.
   - Store raw entries: `{rule_id, quote, fix, type, ...}`.
   - Script *computes* the rating from the entries. Re-run on old files and
     every past session stays consistent with new rules.

2. **Weight the error types.**
   - Grammar error = heavy
   - Portuguese transfer = medium
   - Typo = light
   - Style = zero
   - Turns "almos is just a typo" from a negotiation into literal code.

3. **Counters become a query.**
   - Every error stored with its `rule_id` → "how many prepositions?" is just
     `group by rule_id`.
   - No more manually bumping counters in common_mistakes.md.
   - Tracker becomes a live dashboard instead of a hand-edited file.

4. **Keep snippets, not the full conversation.**
   - Store only flagged lines + the gray-zone items (the "we're vs were" cases).
   - The full conversation is ~10% useful lines; keep the 10%.

5. **Add a `schema_version` field.**
   - Rules keep growing (e.g. #19 "this night" was just added).
   - Versioning means the script can handle old files without breaking.

## The Honest Limit

- **Recognition of errors = fuzzy.** The coach/AI does it. Not deterministic.
- **Scoring + storage = deterministic.** The script only runs *after* the YAML
  is written.
- The "is this an error or not" call stays human/AI no matter what. Any design
  that pretends otherwise is lying to itself.

## Suggested DB Shape

- Two collections: `sessions` and `errors`.
- Error documents reference `session_id`.
- MongoDB is overkill at this scale, but it's a NoSQL learning project, so fine.

## The Real Brain Problem: Context Window

The DB problem is solved by the schema. The *brain* problem is not: the coach
(AI) has a finite context window. Today session_log is 91 lines and fits. After
2 years × 2 sessions/day it won't. So the real question: **what gets injected
into the coach's context at session start, and how do we make sure it's the
relevant 2%?**

That's a genuine **RAG** use case — retrieval-augmented generation applied to
the coach's memory:

1. **profile** — small, stays static.
2. **active rules + current counts** — the "what's biting me lately" view.
3. **last few sessions** — so the coach picks up the thread.
4. **the RAG layer** — pull semantically similar past errors to whatever we're
   discussing ("wait, you did this exact thing back in April").

The shift: instead of *all* history in context, retrieve *just enough* relevant
history per session.

Cheaper trick first — **hierarchical memory** (deterministic, no vectors):
- Old sessions → rolled into monthly summaries.
- Old summaries → rolled into yearly paragraphs.
- Covers the "don't forget who I am" part.

So RAG is the *deep recall* layer for the occasional "what was that thing I
struggled with around July?" moment, not the foundation.

## Making the Coach Better (honest take)

RAG over general English dictionaries/grammar = low value. The coach already
knows English grammar; a grammar RAG is feeding the model rules it already has.

Where RAG *actually* helps the coach:

1. **Portuguese-transfer knowledge base.** The interesting errors are all
   Portuguese interference ("responsible on", "divided with", "essa noite").
   Real literature exists on PT→EN transfer patterns + false friends. Retrieving
   over *that* makes the coach better at *your* English specifically.

2. **Decisions log.** Store past "typo or error?" verdicts, retrieve them,
   keep the coach consistent with itself across sessions. That's the real
   judgment problem from the core — RAG helps here more than any dictionary.

## Language-Agnostic Coach (Italian for a friend)

The system is *already* mostly language-agnostic. The language-specific parts:

- rules file (common_mistakes.md) — per language
- profile — per language
- session log — per language
- knowledge of the learner's L1 → target-language transfer patterns

The core is already neutral: script, DB schema (`rule_id, type, quote, fix`),
rating, vocab-gap mechanism ("(word?)"), flashcards. Add a `language` field and
swap the surface files. Same engine, per-language rules.

Coach = 3 jobs:
- native-speaker judgment → language-agnostic
- consistent tracking → language-agnostic
- catching L1 transfers → per-language (PT→EN vs PT→IT differ)

## Side Quest: Learning RAG (real motivation)

Why RAG? Because I want to learn RAG. Use case is a bit forced at this scale —
doesn't matter. Building a slightly-too-big project is how you learn it.

- Real personal text to work with (sessions, errors, vocab gaps).
- Beginner roadmap to sketch: embeddings → vector store → similarity search →
  retrieval bolted onto a simple LLM call.

## Side Quest: Vocab Gap Storage + Flashcards

- When I get stuck mid-sentence and switch to Portuguese, I flag it (e.g. "(on?)",
  "(atualize?)") — those are vocab gaps.
- Entry: `{pt_word, english, context_sentence, date}`.
  - Front of card = the Portuguese trigger word.
  - Back = the English word + the context sentence where it happened.
- Review engine: **SM-2** spaced repetition algorithm (the one Anki is built on).
  - ~50-100 lines of Python, fully deterministic, no judgment calls.
  - `interval = previous_interval * ease_factor`, graded by Again/Hard/Good/Easy.
- Option A: push cards into Anki via its API.
- Option B (funner): build SM-2 from scratch — mini-Anki for my own gaps.
- NOT the main project. Just a side idea that bolts on later, since vocab gaps
  will already be in the DB.

## Open-Source Edition

Goal: anyone with an LLM key can run the coach free. Site is the front door
(no opencode, no YAML files for users).

- **Code open, data private.** profile / session_log / common_mistakes are
  personal → `.gitignore`, never in the repo. Ship `*.example.md` templates
  instead. Fits the design: surface = user-provided config, core = shared engine.
- **Keys never in the repo.** `LLM_API_KEY` via env var, read at runtime.
  Gitignore it too. #1 open-source beginner mistake.
- **License.** MIT = anyone can fork/use freely (boring default). GPL = forces
  derivatives to stay open. No license = legally nobody can touch it.
- **Forcing function:** code meant for strangers must be readable, documented,
  config-driven. "Would a stranger understand this?" > "works on my machine."

## Notes

- It's **rating**, not "rate" (rate = speed).
- Error recognition is the part that stays fuzzy; spacing out the *review* is the
  part that's pure math — the project splits cleanly at that boundary.

## Open Questions / Next Steps

- [ ] Wait for input from the English teacher (Wednesday).
- [ ] Sketch the YAML schema structure.
- [ ] Decide JSON vs YAML for real.
- [ ] Decide SM-2 side quest now or later.
- [ ] Learn RAG: sketch the beginner roadmap (embeddings → vector store → similarity search).
- [ ] Add `language` field to schema for the language-agnostic version (Italian friend).
- [ ] Sketch the Portuguese-transfer knowledge base content.
- [ ] Decide license (MIT vs GPL) when the repo gets created.
