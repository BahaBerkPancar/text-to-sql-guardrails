from __future__ import annotations

import re

import pytest
from sqlglot import parse

from text_to_sql_guardrails.guard.policy import Policy, load_policy
from text_to_sql_guardrails.guard.validator import ViolationCode, validate


@pytest.fixture(scope="module")
def policy() -> Policy:
    return load_policy("config/policy.toml")


def codes(result: object) -> set[ViolationCode]:
    return {violation.code for violation in result.violations}  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, name FROM customers",
        "SELECT c.name, o.total FROM customers c JOIN orders o ON c.id = o.customer_id",
        "SELECT status, count(*) FROM orders GROUP BY status HAVING count(*) > 1",
        "WITH recent AS (SELECT id, total FROM orders) SELECT id FROM recent",
        "SELECT name FROM customers WHERE id IN (SELECT customer_id FROM orders)",
        "SELECT id FROM customers WHERE EXISTS (SELECT * FROM orders)",
        "SELECT id FROM customers UNION SELECT customer_id FROM orders",
        "SELECT id FROM customers INTERSECT SELECT customer_id FROM orders",
        "SELECT id FROM customers EXCEPT SELECT customer_id FROM orders",
        "(SELECT id FROM customers) UNION (SELECT customer_id FROM orders)",
        "SELECT name, row_number() OVER (ORDER BY created_at) FROM customers",
        "SELECT id FROM products ORDER BY price DESC",
        "SELECT CASE WHEN total > 10 THEN total ELSE 0 END FROM orders",
        "SELECT coalesce(city, country), cast(id AS text) FROM customers",
        "SELECT date_trunc('day', ordered_at), extract(year FROM ordered_at) FROM orders",
        "SELECT abs(total), round(total), greatest(total, 0) FROM orders",
        "SELECT lower(name), upper(name), substring(name FROM 1 FOR 2) FROM products",
        "SELECT string_agg(name, ',') FROM products",
        "SELECT sum(total) OVER () FROM orders",
        "SELECT id FROM orders OFFSET 2",
        "SELECT id FROM orders LIMIT 10 OFFSET 2",
        "SELECT id FROM orders LIMIT 01",
        "SELECT * FROM public.customers",
        'SELECT * FROM "CUSTOMERS"',
        "SELECT * FROM orders -- ; DROP TABLE orders",
        "SELECT /* DROP TABLE staff_salaries */ id FROM orders",
        "WITH customers AS (SELECT id FROM orders) SELECT * FROM customers",
    ],
)
def test_allowed_queries(sql: str, policy: Policy) -> None:
    result = validate(sql, policy)

    assert result.ok, result.violations
    assert result.sql is not None
    assert not result.violations


def test_default_limit_is_added(policy: Policy) -> None:
    result = validate("SELECT id FROM customers", policy)

    assert result.ok
    assert result.sql is not None
    assert result.sql.endswith("LIMIT 100")


def test_literal_limit_is_kept(policy: Policy) -> None:
    result = validate("SELECT id FROM customers LIMIT 12", policy)

    assert result.ok
    assert result.sql is not None
    assert result.sql.endswith("LIMIT 12")


@pytest.mark.parametrize(
    ("sql", "limit_fragment"),
    [
        ("SELECT id FROM customers LIMIT 999", "LIMIT 500"),
        ("SELECT id FROM customers FETCH FIRST 999 ROWS ONLY", "FETCH FIRST 500 ROWS ONLY"),
        ("SELECT id FROM customers UNION SELECT customer_id FROM orders LIMIT 999", "LIMIT 500"),
    ],
)
def test_limit_is_clamped(sql: str, limit_fragment: str, policy: Policy) -> None:
    result = validate(sql, policy)

    assert result.ok
    assert result.sql is not None
    assert result.sql.endswith(limit_fragment)


def test_star_expands_only_allowed_columns(policy: Policy) -> None:
    result = validate("SELECT * FROM customers", policy)

    assert result.ok
    assert result.sql is not None
    selected = result.sql.split(" FROM ", maxsplit=1)[0].casefold()
    assert all(column in selected for column in ("id", "name", "city", "country", "created_at"))
    assert "email" not in selected
    assert "phone" not in selected
    assert "*" not in selected


def test_join_star_expands_each_table_safely(policy: Policy) -> None:
    result = validate(
        "SELECT * FROM customers c JOIN orders o ON c.id = o.customer_id",
        policy,
    )

    assert result.ok
    assert result.sql is not None
    selected = result.sql.split(" FROM ", maxsplit=1)[0].casefold()
    assert "c.name" in selected
    assert "o.total" in selected
    assert "email" not in selected
    assert "*" not in selected


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO orders (id) VALUES (1)",
        "UPDATE orders SET status = 'done'",
        "DELETE FROM orders",
        "MERGE INTO orders o USING orders s ON o.id = s.id WHEN MATCHED THEN DELETE",
        "CREATE TABLE copied AS SELECT * FROM orders",
        "DROP TABLE orders",
        "ALTER TABLE orders ADD COLUMN secret text",
        "TRUNCATE TABLE orders",
        "VACUUM orders",
        "COPY orders TO '/tmp/orders'",
        "SET search_path = public",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "GRANT SELECT ON orders TO public",
        "SELECT * INTO copied FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "SELECT * FROM orders FOR SHARE",
        "WITH removed AS (DELETE FROM orders RETURNING id) SELECT * FROM removed",
        "SELECT * FROM customers USING SAMPLE 10",
        "SELECT * FROM customers TABLESAMPLE SYSTEM (10)",
    ],
)
def test_forbidden_nodes_are_blocked(sql: str, policy: Policy) -> None:
    result = validate(sql, policy)

    assert not result.ok
    assert result.sql is None
    assert ViolationCode.FORBIDDEN_NODE in codes(result)


def test_stacked_statements_are_blocked(policy: Policy) -> None:
    result = validate("SELECT 1; DROP TABLE orders", policy)

    assert not result.ok
    assert codes(result) == {ViolationCode.MULTI_STATEMENT}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT email FROM customers",
        "SELECT c.email FROM customers c",
        "SELECT email FROM (SELECT email FROM customers) private_customer",
        "SELECT * FROM (SELECT c.*, c.email FROM customers c) private_customer",
        "SELECT c FROM customers c",
        "SELECT customers FROM customers",
        "SELECT row_to_json(c) FROM customers c",
        'SELECT "EMAIL" FROM customers',
        "SELECT id AS c FROM customers c ORDER BY c::text",
        "SELECT id AS customers FROM customers ORDER BY customers::text",
        "SELECT id AS c FROM customers c ORDER BY c",
        "SELECT DISTINCT ON (c) id AS c FROM customers c",
        "SELECT x.email FROM customers c CROSS JOIN LATERAL (SELECT c.email) x",
    ],
)
def test_denied_columns_and_whole_rows_are_blocked(sql: str, policy: Policy) -> None:
    result = validate(sql, policy)

    assert not result.ok
    assert ViolationCode.COLUMN_NOT_ALLOWED in codes(result)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM staff_salaries",
        "SELECT * FROM public.staff_salaries",
        'SELECT * FROM "STAFF_SALARIES"',
        "SELECT * FROM private.customers",
        "SELECT * FROM pg_catalog.pg_user",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM pg_stat_activity",
        "SELECT * FROM (VALUES ((SELECT id FROM staff_salaries))) AS v(id)",
        "WITH salaries AS (TABLE staff_salaries) SELECT * FROM salaries",
        "SELECT 1 WHERE 1 IN (TABLE staff_salaries)",
    ],
)
def test_denied_tables_are_blocked(sql: str, policy: Policy) -> None:
    result = validate(sql, policy)

    assert not result.ok
    assert ViolationCode.TABLE_NOT_ALLOWED in codes(result)


@pytest.mark.parametrize(
    ("function", "arguments"),
    [
        ("pg_sleep", "1"),
        ("pg_read_file", "'/tmp/file'"),
        ("pg_ls_dir", "'/tmp'"),
        ("set_config", "'search_path', 'public', false"),
        ("current_setting", "'search_path'"),
        ("dblink", "'connection', 'SELECT 1'"),
        ("lo_import", "'/tmp/file'"),
        ("lo_export", "1, '/tmp/file'"),
        ("version", ""),
        ("query_to_xml", "'SELECT 1', false, false, ''"),
        ("generate_series", "1, 2"),
    ],
)
def test_dangerous_functions_are_blocked(
    function: str,
    arguments: str,
    policy: Policy,
) -> None:
    result = validate(f"SELECT {function}({arguments})", policy)

    assert not result.ok
    assert ViolationCode.FUNCTION_NOT_ALLOWED in codes(result)


def test_policy_can_allow_an_extra_function(policy: Policy) -> None:
    custom_policy = Policy(
        tables=policy.tables,
        default_limit=policy.default_limit,
        max_limit=policy.max_limit,
        extra_functions=frozenset({"md5"}),
    )

    result = validate("SELECT md5(name) FROM customers", custom_policy)

    assert result.ok, result.violations


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 LIMIT -1",
        "SELECT 1 LIMIT $1",
        "SELECT 1 LIMIT 1.5",
        "SELECT 1 LIMIT ALL",
        "SELECT 1 OFFSET -1",
        "SELECT 1 OFFSET $1",
        "SELECT 1 FETCH FIRST $1 ROWS ONLY",
    ],
)
def test_nonliteral_or_negative_limits_are_blocked(sql: str, policy: Policy) -> None:
    result = validate(sql, policy)

    assert not result.ok
    assert ViolationCode.BAD_LIMIT in codes(result)


@pytest.mark.parametrize("sql", ["", "   ", "-- only a comment"])
def test_empty_sql_is_blocked(sql: str, policy: Policy) -> None:
    result = validate(sql, policy)

    assert not result.ok
    assert codes(result) == {ViolationCode.EMPTY}


@pytest.mark.parametrize("sql", ["SELECT (", "SELECT '"])
def test_parse_error_is_reported(sql: str, policy: Policy) -> None:
    result = validate(sql, policy)

    assert not result.ok
    assert codes(result) == {ViolationCode.PARSE_ERROR}


def test_non_select_root_is_reported(policy: Policy) -> None:
    result = validate("VALUES (1)", policy)

    assert not result.ok
    assert ViolationCode.NOT_SELECT in codes(result)


def test_result_sql_is_postgres_and_has_one_outer_limit(policy: Policy) -> None:
    result = validate("SELECT id FROM customers UNION SELECT customer_id FROM orders", policy)

    assert result.ok
    assert result.sql is not None
    assert len(re.findall(r"\bLIMIT\b", result.sql)) == 1
    assert result.sql.endswith("LIMIT 100")


def test_each_set_branch_limit_is_clamped(policy: Policy) -> None:
    result = validate(
        "(SELECT id FROM customers LIMIT 900) UNION "
        "(SELECT customer_id FROM orders LIMIT 800)",
        policy,
    )

    assert result.ok, result.violations
    assert result.sql is not None
    assert result.sql.count("LIMIT 500") == 2
    assert result.sql.endswith("LIMIT 100")


def test_comments_are_removed_from_returned_sql(policy: Policy) -> None:
    result = validate("SELECT 1 -- x */ ; DROP TABLE orders; /*", policy)

    assert result.ok, result.violations
    assert result.sql is not None
    assert "--" not in result.sql
    assert "/*" not in result.sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT E'hello; -- not SQL'",
        "SELECT $$hello; DROP TABLE orders$$",
        r"SELECT U&'d\0061ta; DROP TABLE orders'",
    ],
)
def test_postgres_string_literals_remain_one_statement(sql: str, policy: Policy) -> None:
    result = validate(sql, policy)

    assert result.ok, result.violations
    assert result.sql is not None
    assert len([statement for statement in parse(result.sql, read="postgres") if statement]) == 1


def test_deep_nesting_returns_parse_error_instead_of_raising(policy: Policy) -> None:
    sql = f"SELECT {'(' * 5_000}1{')' * 5_000}"

    result = validate(sql, policy)

    assert not result.ok
    assert ViolationCode.PARSE_ERROR in codes(result)
