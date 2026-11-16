from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from text_to_sql_guardrails.db import get_readonly_engine
from text_to_sql_guardrails.guard.executor import QueryResult
from text_to_sql_guardrails.llm.base import Generation, LlmFailed, LlmNotConfigured
from text_to_sql_guardrails.llm.fake import FakeGenerator
from text_to_sql_guardrails.main import app, get_generator


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_demo_page_has_strict_csp(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "text-to-sql guardrails" in response.text
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp


def test_demo_static_assets_are_served(client):
    javascript = client.get("/static/app.js")
    stylesheet = client.get("/static/style.css")

    assert javascript.status_code == 200
    assert javascript.headers["content-type"].startswith("text/javascript")
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")


def test_demo_javascript_never_uses_inner_html(client):
    javascript = client.get("/static/app.js").text

    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in javascript


@pytest.mark.parametrize("path", ["/static/../main.py", "/static/%2e%2e/main.py"])
def test_static_mount_blocks_traversal(client, path):
    assert client.get(path).status_code == 404


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
            raise SQLAlchemyError(
                "postgresql://secret-user:secret-password@private-host/db"
            )

    app.dependency_overrides[get_readonly_engine] = lambda: BrokenEngine()
    response = client.post("/query", json={"sql": "SELECT id FROM customers"})

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "stage": "database",
        "error": {"code": "QUERY_FAILED", "message": "Database query failed"},
    }


def test_ask_returns_generated_rows_and_usage(client, monkeypatch):
    fake = FakeGenerator(
        [Generation("SELECT id FROM orders", None, "test-model", 11, 4)]
    )
    app.dependency_overrides[get_generator] = lambda: fake
    monkeypatch.setattr(
        "text_to_sql_guardrails.pipeline.run_readonly",
        lambda *args, **kwargs: QueryResult(["id"], [[1]], 1, False, 0.5),
    )

    response = client.post("/ask", json={"question": "Show one order"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["question"] == "Show one order"
    assert body["rows"] == [[1]]
    assert body["attempts"] == [{"sql": "SELECT id FROM orders", "error_code": None}]
    assert body["model"] == "test-model"
    assert body["usage"] == {"input_tokens": 11, "output_tokens": 4}


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (LlmNotConfigured("not configured"), 503, "LLM_NOT_CONFIGURED"),
        (LlmFailed("provider unavailable"), 502, "LLM_FAILED"),
    ],
)
def test_ask_maps_model_service_errors(client, error, status_code, code):
    class FailingGenerator:
        def generate(self, question, schema_prompt, previous):
            raise error

    app.dependency_overrides[get_generator] = lambda: FailingGenerator()

    response = client.post("/ask", json={"question": "Show orders"})

    assert response.status_code == status_code
    assert response.json() == {
        "ok": False,
        "stage": "model",
        "error": {"code": code, "message": str(error)},
        "attempts": [],
    }


@pytest.mark.parametrize("question", ["", "x" * 1_001])
def test_ask_validates_question_length(client, question):
    response = client.post("/ask", json={"question": question})

    assert response.status_code == 422


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


@pytest.mark.pg
def test_ask_end_to_end_aggregate_with_fake_generator(client, pg_engines):
    admin_engine, readonly_engine = pg_engines
    sql = "SELECT status, count(*) AS count FROM orders GROUP BY status ORDER BY status"
    fake = FakeGenerator([Generation(sql, None, "test-model", 20, 8)])
    app.dependency_overrides[get_readonly_engine] = lambda: readonly_engine
    app.dependency_overrides[get_generator] = lambda: fake

    with admin_engine.connect() as connection:
        expected = [list(row) for row in connection.execute(text(sql))]
    response = client.post("/ask", json={"question": "Count orders by status"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["columns"] == ["status", "count"]
    assert body["rows"] == expected
    assert body["row_count"] == len(expected)
