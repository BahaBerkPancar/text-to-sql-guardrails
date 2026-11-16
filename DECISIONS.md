# Decisions

Newest first. One entry per decision: date, what was decided, why, and what was rejected.

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
