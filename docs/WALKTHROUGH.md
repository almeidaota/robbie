# Walkthrough de revisão — migração MongoDB → PostgreSQL

Como revisar: siga a execução do app do início ao fim. Cada item tem o trecho
de código (arquivo:linha) e **o que conferir**. Marque `[x]` quando validar.
Referências de linha apontam para o código no estado atual (pós-migração).

---

## 0. Configuração do ambiente

- [ ] **`.env.example` commitado** — raiz do repo, com placeholders e sem
      segredos. `.env` (real) está no `.gitignore` (linha 7) e há exceção
      `!.env.example` (linha 9) para o exemplo ser versionado.
      Conferir: `git check-ignore .env` → deve listar `.env`;
      `git check-ignore .env.example` → **não** deve listar.
- [ ] **`docker-compose.yml`** — substitui mongo/mongo-express por
      `postgres:17` + `adminer`. Credenciais vêm de `${POSTGRES_USER}` etc.
      (interpolação automática do `.env` do diretório), com defaults locais.
      Conferir: `robbie` (banco) e `robbie/db.py` leem as **mesmas** variáveis.

## 1. `robbie setup` — escreve o `.env`

- [ ] `robbie/cli.py:66 cmd_setup` — imprime "Writing config to .env",
      pergunta a API key (getpass), base URL e modelo (picker
      `_pick_model` cli.py:34).
- [ ] `robbie/config.py:52 write_config` — **atualiza** o `.env` sem apagar
      outras vars: preserva linhas de `POSTGRES_*`, reescreve `LLM_API_KEY`/
      `LLM_BASE_URL`/`LLM_MODEL`, adiciona as que faltam, `chmod 600`.
      Conferir: `tests/test_config.py::test_write_config_updates_existing_key`.

## 2. Carregamento de config — `load_config`

- [ ] `robbie/config.py:38 load_config` — `load_dotenv(ENV_FILE, override=False)`
      → env vars **já definidas vencem** o `.env`. Erros: `ConfigError` se
      faltar `LLM_API_KEY`. Não existe mais `config.toml`/`tomllib`.
      Conferir: `tests/test_config.py::test_env_overrides_dotenv`.

## 3. `robbie activate` — conexão com o banco

- [ ] `robbie/activate.py:58 _connect_db` — tenta `RobbieDB()`; em `DBError`,
      roda `docker compose up -d` (`_compose_up`, activate.py:40) e tenta de
      novo até 5× com 1s de espera.
- [ ] `robbie/db.py:42 RobbieDB.__init__` — monta conexão das vars do `.env`
      (`POSTGRES_HOST/PORT/USER/PASSWORD`), `connect_timeout=3`,
      `autocommit=True`, `row_factory=dict_row`. Se a conexão falhar →
      `DBError` (db.py:37).
- [ ] `robbie/db.py:410 _ensure_database` — cria o banco `robbie_test` (e
      qualquer outro) se não existir, conectando no banco `postgres`.
      Conferir: é isso que permite `RobbieDB(db_name="robbie_test")` nos testes.

## 4. Schema — `_init_schema`

- [ ] `robbie/db.py:74 _init_schema` — `CREATE TABLE IF NOT EXISTS`:
      - `sessions`: `session_id TEXT PK`, `date DATE`, `mode`, `topics JSONB`,
        `vocab_gaps JSONB`, `stored_at TIMESTAMPTZ`
      - `errors`: `id SERIAL PK` (ordem de inserção), `session_id FK → sessions
        ON DELETE CASCADE`, `type/quote/fix/self_caught BOOL`
      - `cards`: `slug TEXT PK`, `contexts JSONB`, `first/last_seen DATE`,
        `ease_factor DOUBLE PRECISION`, `due_date DATE`, `suspended BOOL`
      - índices `idx_errors_session_id` e `idx_cards_due_date`
      Conferir: nomes e tipos batem com o "Storage model" do README.

## 5. ID da sessão — `next_session_id`

- [ ] `robbie/activate.py:27 next_session_id` — consulta `db.session_ids_on`
      (db.py:218, `SELECT session_id FROM sessions WHERE date = %s`) e deriva o
      próximo `YYYY-MM-DD-NN`.
      Conferir: `tests/test_activate.py::test_next_session_id_counts_existing`.

## 6. Wrap-up — persistir a sessão

- [ ] `robbie/activate.py:162 _wrap_up` — `coach.wrap_up(...)` → JSON validado
      por `parse_session` → `db.upsert_session(session)` →
      `db.sync_cards_from_session(session)` → append no session_log.
- [ ] `robbie/db.py:134 upsert_session` — `INSERT ... ON CONFLICT (session_id)
      DO UPDATE`, depois `DELETE FROM errors` + `INSERT` dos erros
      (      `cursor().executemany`). JSONB é envolvido em `Jsonb(...)` (import em
      db.py:27) porque o psycopg3 não adapta dict/list cru.
      Conferir: "facts, never verdicts" — **não** grava rating.
      `tests/test_db.py::test_rating_not_stored`.

## 7. Cards — sync de vocab gaps

- [ ] `robbie/db.py:225 sync_cards_from_session` — agrupa gaps por slug
      (`sm2.card_slug`), lê o card, acumula contextos novos (idempotente por
      sessão), incrementa `times_gapped`, e faz `INSERT ... ON CONFLICT (slug)
      DO UPDATE` tocando só `contexts`, `times_gapped` e `last_seen` —
      o estado SM-2 é preservado.
      Conferir: `tests/test_db.py` (TestCards): criação, append, idempotência,
      duas lacunas na mesma sessão, due/not-due, suspensão.

## 8. `robbie show` — dashboard

- [ ] `robbie/cli.py:83 cmd_show` → `db.all_sessions()` (db.py:206, ordenado por
      `date, session_id`) → `Session.rating()` recomputada (não lida do banco).
      `db.counts_by_type()` (db.py:212) agora é um `GROUP BY type`.
      Conferir: os ratings exibidos mudam se você editar `WEIGHTS` (parser.py:22).

## 9. `robbie review` — repetição espaçada

- [ ] `robbie/review.py:30 review` — `db.due_cards(today)` (db.py:326,
      `WHERE due_date <= %s AND NOT suspended`), e o contador de "ainda vencem"
      usa `db.count_due_cards` (db.py:338) — não há mais `count_documents`.
- [ ] `robbie/review.py:66 _review_one` — a chave agora é `card["slug"]`
      (antes `card["_id"]`). Grade via `db.review_card(slug, grade, today)`
      (db.py:345) → `UPDATE ... RETURNING *`, aplica `sm2.CardState.with_review`
      e persiste `repetitions/ease_factor/interval_days/due_date/last_reviewed`.
      Conferir: `tests/test_db.py::test_review_advances_state` e
      `test_review_unknown_card_raises`.

## 10. `robbie export` — Anki

- [ ] `robbie/cli.py:101 cmd_export` → `db.all_cards()` (db.py:322, ordenado por
      `l1_word`) → `build_deck` (export.py:37) pula cards suspensos e monta o
      `.apkg` com `genanki`. Não toca no banco (one-way).
      Conferir: `tests/test_export.py` (slug no lugar de `_id`).

## 11. Camada determinística — intacta

- [ ] `robbie/parser.py` — `Session.rating()`/`errors_per_100_words()`,
      pesos e clamp. **Não foi alterado** — continuar conferindo só se quiser.
- [ ] `robbie/sm2.py` — `CardState`, `EASE_DELTA`, `card_slug`. **Não alterado.**
- [ ] `robbie/coach.py` — usa `db.all_sessions()`; não dependia do dialeto.
- [ ] `robbie/llm.py` — cliente HTTP; nada de banco.

## 12. Migração dos dados (já executada e validada)

- [ ] Contagens batem entre as fontes: 17 sessions, 93 errors, 14 cards
      (o script de migração foi executado e **excluído** após sucesso).
- [ ] Estado SM-2 dos cards preservado (`repetitions/ease_factor/interval/
      due_date/last_reviewed` não foram recalculados pela migração).
- [ ] Ratings: todos iguais ao Mongo exceto clamp em 0.0 (ex.: 2026-08-20-02
      tinha rating cru −5.6 → 0.0; comportamento correto do `Session.rating()`).
- [ ] Containers antigos removidos: `robbie-mongo` e `robbie-mongo-express`
      parados e deletados; volume `robbie_robbie-mongo-data` apagado.
- [ ] Deps finais sem `pymongo`: `requirements.txt` e `pyproject.toml` só com
      `psycopg[binary]>=3.1` + `python-dotenv` (+ httpx/rich/genanki).

## 13. Testes e smoke

- [ ] `python -m unittest discover -s tests` → **103 OK** (roda contra
      PostgreSQL `robbie_test` via docker; exige `docker compose up -d`).
- [ ] `robbie show` → tabela de sessões com ratings/counts vindos do PG.
- [ ] `robbie export` → gera `robbie_vocab.apkg` com os cards.
- [ ] `robbie review` → lista cards vencidos; grade persiste o novo estado.

---

### Cobertura por arquivo

| Arquivo | Mudança |
|---|---|
| `robbie/db.py` | reescrito (pymongo → psycopg3) |
| `robbie/config.py` | reescrito (config.toml → `.env`) |
| `robbie/cli.py` | só mensagem do `setup` |
| `robbie/activate.py` | `next_session_id` + mensagens |
| `robbie/review.py` | `slug` + `count_due_cards` |
| `robbie/export.py` | sem mudança funcional |
| `robbie/parser.py`, `sm2.py`, `coach.py`, `llm.py` | sem mudança |
| `docker-compose.yml`, `requirements.txt`, `pyproject.toml`, `.gitignore` | atualizados |
| `README.md`, `docs/WORKFLOW.md`, `project_brainstorm.md`, `docs/presentation.html` | atualizados |
