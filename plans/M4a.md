# M4a: Guardrail benchmark (offline, no LLM)

GOAL: Measure the guardrails on their own, without any model: how many attack queries each layer
blocks, whether any denied data or write gets through, and how many correct queries get blocked by
mistake. The results go in the README, and a `--check` mode runs in CI as a regression gate.
M4b will later reuse the same question set with a real model (`--mode llm`), so keep the structure
open for that, but build nothing LLM-related now.

SCOPE: new `bench/` (data + results), new `src/text_to_sql_guardrails/bench/` package, `tests/`,
`pyproject.toml` / `uv.lock` (`pyyaml`, console script `t2s-bench`), `.github/workflows/test.yml`,
`README.md` (new "Benchmark" section), `DECISIONS.md`, `CHANGELOG.md`.

DO NOT TOUCH: `plans/`, `config/policy.toml`, `migrations/`, `llm/`, `pipeline.py`, `AGENTS.md`,
`CLAUDE.md`. `guard/` only if the benchmark finds a real bypass: then fix it with a regression test
and list it first in NOTES as `BYPASS FOUND: <sql>`. Never weaken a test or drop an attack to make
the numbers look better. Never read `.env`. No network calls.

TEST DATABASE: `TEST_DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:55432/app` (superuser,
already running). The benchmark sets up schema, seed and read-only role itself via the existing
setup code, like the pg test fixtures do.

STEPS:
1. **`bench/questions.yaml`** — at least 40 normal questions about the shop data, each with `id`,
   `question` (plain English, for M4b), `gold_sql`, `category` (simple, filter, join, aggregate,
   group_having, date, window, cte, subquery, set_op) and `difficulty` (easy/medium/hard).
   Every gold query uses only allowed columns, has a deterministic `ORDER BY`, and returns ≤ 100 rows,
   so the injected LIMIT cannot change its result.
2. **`bench/attacks.yaml`** — at least 100 distinct attack SQL strings, each with `id`, `sql`,
   `category`, `note`. At least these categories, ≥ 5 each: `write` (INSERT/UPDATE/DELETE/MERGE),
   `ddl` (CREATE/DROP/ALTER/TRUNCATE/GRANT), `stacked`, `comment_trick`, `denied_column`
   (email/phone via alias, subquery, CTE, LATERAL, `*` on joins, WHERE/ORDER BY oracles),
   `denied_table` (staff_salaries, quoted/case/schema tricks), `system_catalog`
   (pg_catalog, information_schema, pg_roles, pg_settings…), `whole_row` (row refs, alias shadowing,
   to_json/row_to_json), `dangerous_function` (pg_sleep, pg_read_file, set_config, dblink,
   lo_*, nextval/setval, advisory locks, pg_terminate_backend…), `limit_escape` (big/negative/
   non-literal LIMIT, FETCH, set-op branches, OFFSET tricks), `dos` (cartesian joins,
   generate_series, recursive CTEs, huge repeat()), `encoding` (E'', $$, U&, unicode identifiers).
   Include every bypass candidate already tested in `tests/test_validator.py` plus new ones of your own.
3. **Runner** `src/text_to_sql_guardrails/bench/guardrails.py` + CLI `t2s-bench --mode guardrails
   [--check] [--out bench/results]`. For each attack, run three configurations and record the outcome:
   - `validator_only`: `validate()` decision (blocked + violation codes, or passed).
   - `db_only`: the **raw** SQL on the read-only engine through `run_readonly` (validator skipped) —
     outcome `blocked_permission`, `blocked_readonly`, `timeout`, `error`, or `passed`.
   - `full`: validator, then the rewritten SQL on the read-only engine — the real `/query` path.
   For every query that **passes** in any configuration, run two harm checks:
   - **leak check**: fetch the real sensitive values with the admin engine (all customer emails and
     phones, all salary values, staff names) and flag the result if any returned cell contains one.
   - **write check**: a checksum of all tables (row counts + a hash of the data) before and after the
     whole attack run must be identical.
   Use a short timeout for the benchmark (e.g. 1000 ms) so `dos` attacks finish quickly.
4. For each normal question: `full` path on `gold_sql`; compare its rows with the same `gold_sql`
   run on the admin engine (exact, ordered). Outcomes `ok`, `false_block` (validator blocked it),
   `mismatch` (rewrite changed the result), `error`.
5. **Results**: `bench/results/guardrails.json` (per-query outcomes, metrics, versions, timestamp)
   and `bench/results/guardrails.md` with:
   - a per-layer table: attacks blocked by validator alone / by DB layer alone / by the full stack,
     as counts and percentages, plus harmful passes (leak or write) per configuration;
   - a per-category table for the full stack;
   - normal-query table: ok / false_block / mismatch counts and the false-block rate;
   - a list of every attack the **DB layer alone** lets through (this shows why the validator matters)
     and every attack the **validator alone** lets through (this shows why the DB layer matters).
   Copy the summary tables into README "Benchmark" between `<!-- bench:guardrails:start -->` and
   `<!-- bench:guardrails:end -->` markers, rewritten by the CLI with `--update-readme`.
6. **`--check`**: exit 1 if the full stack has any harmful pass (leak or write), any attack that
   passes the full stack and is not in an explicit `allowed_to_pass` list in attacks.yaml (with a
   reason, e.g. a harmless literal), or any normal question that is not `ok`. Exit 0 otherwise.
7. **Tests**: unit tests for loading/validating the YAML files (unique ids, required fields,
   category counts ≥ the minimums above) and for metric computation on fake outcomes; a `pg`
   test that runs the benchmark on a small subset and checks the JSON shape and that `--check`
   fails when a harmful pass is injected (e.g. a fake outcome).
8. **CI**: after pytest, run `uv run t2s-bench --mode guardrails --check` against the CI Postgres service.
9. Docs: README Benchmark section (what is measured, how to run, the tables), DECISIONS (why three
   configurations; why the leak check uses real values; `allowed_to_pass` policy), CHANGELOG.

DONE WHEN:
- `uv run pytest && uv run ruff check .` pass.
- `TEST_DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:55432/app uv run pytest -m pg` passes.
- `TEST_DATABASE_URL=... uv run t2s-bench --mode guardrails --check --update-readme` exits 0, and
  the report shows ≥ 100 attacks, ≥ 40 questions, full-stack harmful passes = 0, false blocks = 0.
- In NOTES, give the headline numbers: block rate per configuration, harmful passes per
  configuration, false-block rate.

ESTIMATE: 75–90 min.

REPORT: end with the report contract (CHANGED / EVIDENCE / ESTIMATE vs ACTUAL / NOTES / VERDICT).
Do not commit, do not push.
