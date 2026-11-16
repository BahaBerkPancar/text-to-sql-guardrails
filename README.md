# text-to-sql-guardrails

Turn plain-English questions into safe, read-only PostgreSQL queries with validation guardrails.

## Setup

```bash
uv sync
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
