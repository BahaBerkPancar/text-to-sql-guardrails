# Changelog

## Unreleased
- Replace the template item API with a deterministic demo-shop database and guarded `POST /query`
  endpoint.
- Add a policy-derived read-only PostgreSQL role, read-only transactions, statement timeouts, and
  capped JSON-safe query results.
- Add PostgreSQL integration coverage and an end-to-end Docker smoke query.
- Add a policy-driven SQL validator that allows read-only queries, hides sensitive columns and
  enforces safe row limits.
- Project created.
