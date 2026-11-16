# text-to-sql-guardrails

Turn plain-English questions into safe, read-only PostgreSQL queries with validation guardrails.

## Setup

The Docker stack migrates and seeds PostgreSQL, creates the policy-derived read-only role, and then
starts the API:

```bash
cp .env.example .env
docker compose up --build
```

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

## Ask a question

`POST /ask` turns a plain-English question into SQL, validates it against the same policy as
`POST /query`, and executes it with the restricted database role:

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H 'content-type: application/json' \
  -d '{"question":"How many orders have each status?"}'
```

The default model is `claude-opus-5-5` at `medium` effort. Configure it with `LLM_MODEL`,
`LLM_EFFORT`, and `LLM_TIMEOUT_S`. A validator or ordinary database error may be sent back to the
model for one repair attempt; permission denials and timeouts stop immediately. Every generated SQL
candidate still passes through the validator, read-only role, transaction, timeout, and row cap.

## Development

Run the tests:

```bash
uv run pytest && uv run ruff check .
```

## Benchmark

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

## How this repo is organised

- `AGENTS.md` – rules for coding agents (Claude Code reads it through `CLAUDE.md`)
- `DECISIONS.md` – why things are the way they are
- `CHANGELOG.md` – what changed in each release
