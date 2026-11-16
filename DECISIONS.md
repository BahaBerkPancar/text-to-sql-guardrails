# Decisions

Newest first. One entry per decision: date, what was decided, why, and what was rejected.

## 2026-11-17 – Make live benchmarking explicit, comparable, and reproducible
Live-model benchmark commands estimate the worst-case cost and stop before constructing a model
client unless `--yes-spend` is present. Implicit paid calls were rejected because a typo or routine
test command must not spend money. Fake mode returns each gold SQL and declines attacks so the real
pipeline, reports, and database checks can be tested offline; treating fake results as model
performance or publishing them to the normal results directory was rejected.

Result correctness compares cell values rather than aliases. Rows are order-insensitive unless the
gold query's outermost statement has `ORDER BY`, and numeric values allow an absolute difference of
0.01. Exact SQL-text comparison was rejected because equivalent SQL can use different joins,
aliases, and expressions, while always ignoring order would miss ordering mistakes users asked for.

Per-model prices live in a dated configuration file, cache reads and writes use their provider
multipliers, and unknown models report a null cost. Reporting zero for an unknown price was rejected
because it would present missing information as a free run.

## 2026-11-17 – Make the database executor a one-statement, stateless boundary
Generated SQL runs through psycopg's prepared extended-query protocol even when it has no bind
parameters. The simple protocol was rejected because it accepts multiple semicolon-separated
commands in one execute, allowing a raw query to change session settings after a harmless SELECT.

Every connection in a read-only engine runs `DISCARD ALL` when checked back into its pool. Rollback
alone was rejected because session advisory locks and session settings survive transaction end and
can affect a later request that reuses the connection.

## 2026-11-16 – Benchmark the validator, database boundary, and full stack separately
The offline corpus runs in three configurations: validator only, raw SQL through the restricted
database executor, and the validator's rewritten SQL through that executor. A single aggregate
score was rejected because it would hide which independent layer catches an attack and which layer
needs regression coverage.

Leak checks compare successful result cells with the database's real customer emails, phone
numbers, salaries, and staff names. Checking only column names or SQL text was rejected because
aliases, expressions, whole-row values, and serialization can remove the original label while the
sensitive value still escapes. A before/after content hash separately detects writes.

An attack may pass the full stack only with a version-controlled `allowed_to_pass` reason for a
demonstrably harmless case, such as SQL-looking text inside a literal or a limit safely clamped by
the validator. Allowlisting harmful behavior or adding an exception merely to improve the score is
not permitted; new unexplained passes fail the benchmark gate.

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
