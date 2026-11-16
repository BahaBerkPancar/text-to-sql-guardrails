# Build plan: text-to-sql-guardrails

Written 2026-11-16. Source idea: vault `knowledge/project-ideas-backlog.md` (#1). Project #2 in the backlog
(Model Regression Detection) will later run as a CI job against this project's benchmark.

## What it is
A FastAPI service that turns a plain-English question into a PostgreSQL query and runs it **safely**.
The point of the portfolio piece is the guardrails, not the prompt: an LLM can write any SQL, so
everything it writes passes through layers that each block a different failure on their own.

```
question ──► LLM generator ──► [1] SQL validator (sqlglot AST) ──► [2] read-only DB role ──► [3] read-only txn
                                    single SELECT, allowlisted           SELECT grants only          statement_timeout,
                                    tables/columns/functions,            on allowed tables/columns   row cap
                                    LIMIT injected or clamped
             ◄── answer: sql, rows, or the block reason (machine-readable code) ──┘
```

Defense in depth: the validator is the main gate, but even if it is bypassed the database role cannot
write or read denied data, and the transaction cannot run long or return too many rows.

## Demo data
A small shop schema (seeded, deterministic): `customers`, `products`, `orders`, `order_items`,
plus sensitive data that must never come back: the columns `customers.email`, `customers.phone`
and the whole table `staff_salaries`. The allowlist lives in `config/policy.toml`.

## Milestones
| # | Name | Contents | Needs MF? |
|---|------|----------|-----------|
| M1 | Guardrail core | `config/policy.toml` + sqlglot validator: one statement, SELECT/CTE/set-ops only, no DML/DDL anywhere in the tree, table/column/function allowlists, system catalogs blocked, LIMIT injected/clamped, rewritten SQL out, machine-readable violation codes. 40+ attack/allow unit tests. No DB, no LLM. | No |
| M2 | Safe executor + demo DB | Replace the template `items` code. Alembic migration for the shop schema, deterministic seed, `readonly` Postgres role with column-level SELECT grants, executor with `SET TRANSACTION READ ONLY`, `statement_timeout`, fetch cap. Integration tests against real Postgres (compose locally, `services: postgres` in CI). `POST /query` (raw SQL → validate → run). | No |
| M3 | LLM generation | `SqlGenerator` interface; `AnthropicGenerator` (model + effort from settings, default `claude-opus-5-5`; M4 compares cheaper ones) with a schema prompt built from the policy; one self-repair retry that feeds the validator's error back; `FakeGenerator` for tests. `POST /ask`. Tests never call the network. | API key to try it live |
| M4 | Benchmark (M4a offline guardrails, M4b live model) | `bench/questions.yaml` (~40 questions with gold SQL, compared by result set) and `bench/attacks.yaml` (~30 prompt-injection / exfiltration / write attempts). `uv run bench` writes `bench/results.json` + a Markdown table: execution accuracy, block rate on attacks, false-block rate on normal questions, latency, cost. | API key |
| M5 | Showcase | README: diagram, guardrail list, benchmark table, how to run. Tiny web page at `/` (question box → SQL + table or block reason). Demo GIF. CI green with Postgres. | Push + making the repo public |

Then: project #2 (regression detection) uses M4's benchmark as its test suite.

## Ground rules
- Builders: Codex via `~/.mf/bin/codex-task`, one milestone at a time; reviews by the `reviewer` agent; hub commits locally after review. No pushes without MF.
- Every milestone: `uv run pytest && uv run ruff check .` green; new behaviour has tests; `DECISIONS.md` and `CHANGELOG.md` updated.
- Never read `.env`. Port 8000 is taken by pulse locally: use `API_PORT=8010` for compose/smoke runs.
