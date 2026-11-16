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

## How this repo is organised

- `AGENTS.md` – rules for coding agents (Claude Code reads it through `CLAUDE.md`)
- `DECISIONS.md` – why things are the way they are
- `CHANGELOG.md` – what changed in each release
