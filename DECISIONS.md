# Decisions

Newest first. One entry per decision: date, what was decided, why, and what was rejected.

## 2026-11-16 – Generate structured SQL with Claude behind the guardrails
Claude Opus 5.5 at medium effort is the initial default because correctness is the priority for the
first end-to-end version. Both model and effort remain configurable, and M4's benchmark will compare
cheaper models and effort levels before the default changes.

The generator uses Anthropic structured JSON output rather than tool use. The response has exactly
two fields (`sql` and `cannot_answer`), which keeps parsing narrow while the existing validator and
database role remain the authority. The stable system and policy-filtered schema prompt use prompt
caching; the untrusted question and any retry feedback remain separate message turns.

A validation failure or ordinary query failure gets one repair attempt because those failures may
come from model mistakes. Permission failures and statement timeouts are not retried: they show a
guardrail has stopped the query, and asking the model to work around that result would weaken the
boundary.

## 2026-11-16 – Enforce database access from the same policy as validation
The setup command generates column-level PostgreSQL grants from `config/policy.toml`, so the
database role cannot read a sensitive column even if application validation is bypassed. A manually
maintained second allowlist was rejected because it could drift from the validator policy.

Every execution also starts an explicitly read-only transaction, applies a transaction-local
statement timeout, fetches at most one row beyond the response cap, and rolls back. PostgreSQL
functions such as `pg_sleep` remain executable by `PUBLIC`; removing function privileges globally
would affect unrelated roles, so the timeout is the layer-3 backstop for them.

## 2026-11-16 – Return guarded query failures as successful HTTP exchanges
`POST /query` returns HTTP 200 with `ok=false` and a machine-readable validation or database stage.
These outcomes are expected answers to untrusted generated SQL rather than transport failures. HTTP
422 remains reserved for an invalid request shape, including SQL over 10,000 characters.

## 2026-11-16 – Keep PostgreSQL integration tests optional locally
Tests marked `pg` skip when `TEST_DATABASE_URL` is absent, keeping the ordinary unit suite usable
without Docker. CI always provides PostgreSQL and runs those tests, so the database-specific
permission, timeout, migration, and seed behavior is still mandatory before merging.

## 2026-11-16 – Parse SQL into an allowlisted AST
The guardrail parses PostgreSQL with sqlglot and qualifies queries against a schema containing only
allowed columns. Regex checks were rejected because comments, quoting, aliases, CTEs and nested
queries make text matching unsafe. Tables, columns and functions use allowlists rather than
denylists so newly added database objects or sqlglot expression types fail closed.

Allowed function classes are limited to common aggregates (`array_agg`, `avg`, `count`, `min`,
`max`, `sum`, standard deviation, variance and percentiles), strings (`concat`, `initcap`, `length`,
`lower`, `replace`, `string_agg`, `substring`, `trim`, `upper`), math (`abs`, `ceil`, `floor`, `mod`, `power`,
`round`, `sqrt`, `greatest`, `least`), date/time (`current_date`, `current_time`,
`current_timestamp`, date add/subtract/difference/truncate and `extract`), null/type operations
(`coalesce`, `nullif`, `cast`, `try_cast`) and window helpers (`dense_rank`, `lag`, `lead`, `rank`,
`row_number`). `CASE`, `EXISTS` and window framing are read-only AST operations and remain
available. Any other function needs an explicit policy entry.

PostgreSQL whole-row references are rejected even after qualification. A reference such as
`row_to_json(c)` can serialize columns omitted from the policy because it addresses the underlying
row type, not the qualified projection.

## 2026-11-16 – Project created from the `fastapi-app` template
Why: same layout, test setup and CI as the other projects, so nothing has to be set up by hand.
