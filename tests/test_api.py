from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from text_to_sql_guardrails.db import get_readonly_engine
from text_to_sql_guardrails.main import app


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_schema_exposes_only_policy_columns(client):
    response = client.get("/schema")

    assert response.status_code == 200
    tables = response.json()["tables"]
    assert set(tables) == {"customers", "products", "orders", "order_items"}
    assert "email" not in tables["customers"]
    assert "phone" not in tables["customers"]


def test_blocked_query_never_touches_database(client):
    class FailIfUsedEngine:
        def connect(self):
            raise AssertionError("database must not be touched for blocked SQL")

    app.dependency_overrides[get_readonly_engine] = lambda: FailIfUsedEngine()
    response = client.post("/query", json={"sql": "SELECT email FROM customers"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["stage"] == "validator"
    assert {item["code"] for item in body["violations"]} == {"COLUMN_NOT_ALLOWED"}


def test_query_rejects_more_than_10000_characters(client):
    response = client.post("/query", json={"sql": "x" * 10_001})

    assert response.status_code == 422


def test_query_database_error_is_safe(client):
    class BrokenEngine:
        def connect(self):
            raise SQLAlchemyError("postgresql://secret-user:secret-password@private-host/db")

    app.dependency_overrides[get_readonly_engine] = lambda: BrokenEngine()
    response = client.post("/query", json={"sql": "SELECT id FROM customers"})

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "stage": "database",
        "error": {"code": "QUERY_FAILED", "message": "Database query failed"},
    }


@pytest.mark.pg
def test_end_to_end_aggregate(client, pg_engines):
    admin_engine, readonly_engine = pg_engines
    app.dependency_overrides[get_readonly_engine] = lambda: readonly_engine
    sql = "SELECT status, count(*) AS count FROM orders GROUP BY status ORDER BY status"

    with admin_engine.connect() as connection:
        expected = [list(row) for row in connection.execute(text(sql))]
    response = client.post("/query", json={"sql": sql})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["columns"] == ["status", "count"]
    assert body["rows"] == expected
    assert body["row_count"] == len(expected)
    assert body["truncated"] is False
