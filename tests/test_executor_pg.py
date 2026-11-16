from __future__ import annotations

import time

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from text_to_sql_guardrails.db import create_readonly_engine
from text_to_sql_guardrails.guard.executor import (
    QueryFailed,
    QueryPermissionDenied,
    QueryTimeout,
    run_readonly,
)
from text_to_sql_guardrails.models import Order

pytestmark = pytest.mark.pg


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT email FROM customers",
        "SELECT * FROM staff_salaries",
        "SELECT c FROM customers c",
        "DELETE FROM orders",
        "CREATE TABLE x(i int)",
    ],
)
def test_layer_2_role_blocks_raw_sql_and_writes(pg_engines, sql):
    admin_engine, readonly_engine = pg_engines
    with admin_engine.connect() as connection:
        before = connection.scalar(select(func.count()).select_from(Order))

    with pytest.raises(DBAPIError) as caught, readonly_engine.begin() as connection:
        connection.execute(text(sql))

    assert caught.value.orig.sqlstate in {"25006", "42501"}
    with admin_engine.connect() as connection:
        after = connection.scalar(select(func.count()).select_from(Order))
    assert after == before == 1_000


def test_layer_2_role_allows_policy_columns(pg_engines):
    _, readonly_engine = pg_engines

    with readonly_engine.connect() as connection:
        name = connection.scalar(text("SELECT name FROM customers WHERE id = 1"))

    assert name == "Customer 001"


def test_layer_2_grants_block_writes_even_when_read_only_default_is_disabled(
    pg_engines,
):
    _, readonly_engine = pg_engines

    with readonly_engine.connect() as connection:
        connection.execute(text("SET default_transaction_read_only = off"))
        connection.commit()
        with pytest.raises(DBAPIError) as caught:
            connection.execute(text("DELETE FROM orders WHERE id = -1"))

    assert caught.value.orig.sqlstate == "42501"


def test_executor_preserves_colons_and_percent_signs_in_literals(pg_engines):
    _, readonly_engine = pg_engines

    result = run_readonly(
        "SELECT name FROM products WHERE name <> 'a:b %' ORDER BY id LIMIT 1",
        readonly_engine,
        timeout_ms=3_000,
        max_rows=10,
    )

    assert result.rows == [["Product 01"]]

    literal = run_readonly(
        "SELECT 'a%' AS x, 't:1' AS y, "
        "(SELECT count(*) FROM products WHERE name LIKE 'Product 0%') AS n",
        readonly_engine,
        timeout_ms=3_000,
        max_rows=10,
    )
    assert literal.rows[0][:2] == ["a%", "t:1"]
    assert literal.rows[0][2] == 9


def test_executor_rejects_stacked_statements_without_validator(pg_engines):
    _, readonly_engine = pg_engines

    with pytest.raises(QueryFailed):
        run_readonly(
            "SELECT 1; SELECT 2",
            readonly_engine,
            timeout_ms=3_000,
            max_rows=10,
        )


def test_readonly_pool_discards_session_advisory_locks(pg_engines):
    _, fixture_readonly_engine = pg_engines
    engine = create_readonly_engine(
        fixture_readonly_engine.url,
        pool_size=1,
        max_overflow=0,
    )
    try:
        run_readonly(
            "SELECT pg_advisory_lock(7)",
            engine,
            timeout_ms=3_000,
            max_rows=10,
        )

        result = run_readonly(
            "SELECT count(*) FROM pg_locks "
            "WHERE locktype = 'advisory' AND pid = pg_backend_pid()",
            engine,
            timeout_ms=3_000,
            max_rows=10,
        )

        assert result.rows == [[0]]
    finally:
        engine.dispose()


def test_layer_3_timeout_without_validator(pg_engines):
    admin_engine, _ = pg_engines
    started = time.perf_counter()

    with pytest.raises(QueryTimeout):
        run_readonly("SELECT pg_sleep(5)", admin_engine, timeout_ms=300, max_rows=10)

    assert time.perf_counter() - started < 2


def test_layer_3_row_cap_without_validator(pg_engines):
    admin_engine, _ = pg_engines

    result = run_readonly(
        "SELECT id FROM orders ORDER BY id",
        admin_engine,
        timeout_ms=3_000,
        max_rows=10,
    )

    assert result.row_count == 10
    assert result.rows == [[number] for number in range(1, 11)]
    assert result.truncated is True


def test_executor_maps_read_only_failures(pg_engines):
    _, readonly_engine = pg_engines

    with pytest.raises(QueryPermissionDenied):
        run_readonly(
            "DELETE FROM orders", readonly_engine, timeout_ms=3_000, max_rows=10
        )
