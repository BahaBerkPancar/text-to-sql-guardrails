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

## Development

Run the tests:

```bash
uv run pytest && uv run ruff check .
```

## How this repo is organised

- `AGENTS.md` – rules for coding agents (Claude Code reads it through `CLAUDE.md`)
- `DECISIONS.md` – why things are the way they are
- `CHANGELOG.md` – what changed in each release
