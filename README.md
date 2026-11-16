# text-to-sql-guardrails

Turn plain-English questions into PostgreSQL queries without trusting the model that writes them.

![Demo: one allowed query followed by four blocked attacks](docs/demo.gif)

## Why

An LLM that can write SQL can write *any* SQL: it can expose a sensitive column, call a dangerous
function, hide a write inside a CTE, or simply make a costly mistake. This project treats generated
SQL as untrusted input. A model candidate crosses a policy-aware AST validator and independent
PostgreSQL controls before any rows are returned.

## Safety layers

![Question to model to validator to read-only role to read-only transaction to result](docs/architecture.svg)

| Layer | What it stops | Where |
| --- | --- | --- |
| Structured model boundary | Free-form output and malformed response shapes | `llm/anthropic_gen.py` |
| Policy-aware AST validator | Writes, stacked statements, denied tables or columns, unsafe functions, whole-row leaks and unbounded results | `guard/validator.py` |
| Restricted PostgreSQL role | Access to objects and columns not granted by the same policy | `guard/roles.py` |
| Read-only transaction | Writes that reach the database boundary | `guard/executor.py` |
| Statement timeout and row cap | Long-running statements and oversized responses | `guard/executor.py` |

The model can repair an ordinary mistake once, but it never decides whether its own SQL is safe.

## Try it

The Docker stack migrates and seeds PostgreSQL, creates the policy-derived read-only role, and then
starts the API:

```bash
API_PORT=8010 docker compose up --build
```

Open <http://127.0.0.1:8010/> for the offline demo page. **Run SQL** works with no model
credentials. **Ask** clearly reports `LLM_NOT_CONFIGURED` until an Anthropic Console API key or a
local Anthropic CLI login is available.

Run guarded SQL directly:

```bash
curl -X POST http://127.0.0.1:8010/query \
  -H 'content-type: application/json' \
  -d '{"sql":"SELECT status, count(*) AS count FROM orders GROUP BY status ORDER BY status"}'
```

Or ask a natural-language question:

```bash
curl -X POST http://127.0.0.1:8010/ask \
  -H 'content-type: application/json' \
  -d '{"question":"How many orders have each status?"}'
```

To configure credentials and passwords explicitly, copy `.env.example` to `.env` and replace its
placeholders. Never commit that file.

### Local development

For local development with PostgreSQL already running:

```bash
uv sync
cp .env.example .env  # edit the placeholder passwords and URLs
uv run t2s-setup
uv run uvicorn text_to_sql_guardrails.main:app --reload
```

Authenticate Claude by setting `ANTHROPIC_API_KEY` in `.env`, or authenticate the local Anthropic
CLI with `ant auth login`. The client is created only when `/ask` is called, so `/health`, `/schema`,
and `/query` work without model credentials.
The default model is `claude-opus-5-5` at `medium` effort. Configure it with `LLM_MODEL`,
`LLM_EFFORT`, and `LLM_TIMEOUT_S`. A validator or ordinary database error may be sent back to the
model for one repair attempt; permission denials and timeouts stop immediately. Every generated SQL
candidate still passes through the validator, read-only role, transaction, timeout, and row cap.

## Offline benchmark: 0 harmful passes, 0 false blocks

The offline benchmark measures the parser/validator, the PostgreSQL read-only role and transaction,
and the complete stack separately. It runs version-controlled attack SQL without an LLM, checks
successful results against real sensitive values, verifies a before/after hash of every shop table,
every public sequence, and compares normal gold queries exactly against the admin result.

Run it only against a disposable PostgreSQL database; it rebuilds the `public` schema:

```bash
TEST_DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:55432/app \
  uv run t2s-bench --mode guardrails --check --update-readme
```

`--check` fails on harmful full-stack passes, unapproved full-stack passes, false blocks,
mismatches, or execution errors. A harmless attack may pass only when its YAML entry has an
`allowed_to_pass` reason. JSON and Markdown reports are written to `bench/results` by default.

The validator and database boundary are both necessary: the validator blocks unsafe reads that a
database read-only role can still permit, while the role and transaction remain effective if an
application validation defect lets a candidate through.

<!-- bench:guardrails:start -->
Full stack: **rejected 106**, **neutralized 16** (`allowed_to_pass`, rewritten to safe SQL), **harmful 0**.

| Configuration | Validator | Permission | Read-only | Timeout | Error | Passed | Harmful |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Validator only | 106 | 0 | 0 | 0 | 0 | 24 | 0 |
| Database only | 0 | 38 | 15 | 11 | 31 | 35 | 0 |
| Full stack | 106 | 0 | 0 | 7 | 1 | 16 | 0 |

| Full-stack category | Validator | Permission | Read-only | Timeout | Error | Neutralized | Harmful |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `comment_trick` | 2 | 0 | 0 | 0 | 0 | 6 | 0 |
| `dangerous_function` | 16 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ddl` | 12 | 0 | 0 | 0 | 0 | 0 | 0 |
| `denied_column` | 14 | 0 | 0 | 0 | 0 | 1 | 0 |
| `denied_table` | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| `dos` | 4 | 0 | 0 | 7 | 0 | 0 | 0 |
| `encoding` | 3 | 0 | 0 | 0 | 1 | 4 | 0 |
| `limit_escape` | 7 | 0 | 0 | 0 | 0 | 5 | 0 |
| `stacked` | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| `system_catalog` | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| `whole_row` | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| `write` | 10 | 0 | 0 | 0 | 0 | 0 | 0 |

| Normal queries | OK | False blocks | Mismatches | Errors | False-block rate |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 40 | 40 | 0 | 0 | 0 | 0.00% |
<!-- bench:guardrails:end -->

### Live-model benchmark

The live-model mode measures execution accuracy for the 40 natural-language questions, retry
rescues, prompt-injection handling, latency, token usage, and estimated model cost. By default it
only prints a worst-case cost estimate and makes no model request:

```bash
uv run t2s-bench --mode llm --model claude-haiku-5-5 --effort low
```

Review the estimate, configure a Console API key or run `ant auth login`, then explicitly add
`--yes-spend` to make paid requests. A Claude Code login does not authenticate this command. Use
`--fake` to exercise the same pipeline offline; fake output goes to a temporary directory unless
`--out` is supplied and is always marked as fake. Price entries are dated estimates, so check the
current provider prices before quoting a result.

No live-model benchmark numbers have been published yet.

<!-- bench:llm:start -->
Live results will appear here only after an explicitly approved run.
<!-- bench:llm:end -->

## Limitations

- PostgreSQL is the only supported database and several protections rely on PostgreSQL roles and
  read-only transactions.
- The table, column and function allowlist must be updated deliberately as the application schema
  changes.
- A query can be safe but still answer the question incorrectly. Guardrails constrain behavior;
  they do not prove semantic accuracy.
- The database-only layer permits some harmless catalog reads, which is why the validator remains
  part of the full stack.
- The statement timeout limits resource abuse but is not a general-purpose query-cost estimator.
- Live-model accuracy and prompt-injection numbers have not been published yet.

## Development

Install dependencies and run the complete local checks:

```bash
uv sync
uv run pytest && uv run ruff check .
TEST_DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:55432/app uv run pytest -m pg
API_PORT=8010 ./scripts/smoke.sh
```

The integration database must be disposable because the PostgreSQL tests rebuild its `public`
schema. To regenerate the GIF and screenshots, start the application separately and run:

```bash
API_PORT=8010 docker compose up -d --build
uv run python scripts/record_demo.py --url http://127.0.0.1:8010
API_PORT=8010 docker compose down
```

The recorder starts no services and makes no model request. It uses system Chrome in headless mode
and `/opt/homebrew/bin/ffmpeg`, writes two PNGs plus `docs/demo.gif`, and removes its temporary
Chrome profile when it exits.

## Project layout

- `src/text_to_sql_guardrails/guard/` — AST validation and PostgreSQL enforcement
- `src/text_to_sql_guardrails/llm/` — structured SQL generation behind a narrow interface
- `src/text_to_sql_guardrails/web/` — dependency-free demo page served by FastAPI
- `bench/` — version-controlled attacks, normal questions and benchmark reports
- `scripts/` — Docker smoke test and reproducible demo recorder
- `tests/` — unit tests plus opt-in PostgreSQL integration coverage
- `DECISIONS.md` — dated technical decisions and rejected alternatives
- `CHANGELOG.md` — user-visible changes under development
