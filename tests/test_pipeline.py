from __future__ import annotations

import pytest

from text_to_sql_guardrails.config import Settings
from text_to_sql_guardrails.guard.executor import (
    QueryFailed,
    QueryPermissionDenied,
    QueryResult,
    QueryTimeout,
)
from text_to_sql_guardrails.guard.policy import load_policy
from text_to_sql_guardrails.llm.base import Generation, LlmRefused
from text_to_sql_guardrails.llm.fake import FakeGenerator
from text_to_sql_guardrails.pipeline import answer

POLICY = load_policy("config/policy.toml")


def _generation(sql=None, cannot_answer=None, input_tokens=10, output_tokens=5):
    return Generation(sql, cannot_answer, "test-model", input_tokens, output_tokens)


def _query_result():
    return QueryResult(["id"], [[1]], 1, False, 0.25)


def test_pipeline_succeeds_on_first_try(monkeypatch):
    monkeypatch.setattr(
        "text_to_sql_guardrails.pipeline.run_readonly",
        lambda *args, **kwargs: _query_result(),
    )
    generator = FakeGenerator([_generation("SELECT id FROM orders")])

    result = answer("Show orders", generator, POLICY, object(), Settings())

    assert result.ok is True
    assert result.query_result == _query_result()
    assert result.usage.input_tokens == 10
    assert result.attempts[0].error_code is None
    assert len(generator.calls) == 1


def test_validator_error_is_given_to_one_repair_attempt(monkeypatch):
    monkeypatch.setattr(
        "text_to_sql_guardrails.pipeline.run_readonly",
        lambda *args, **kwargs: _query_result(),
    )
    generator = FakeGenerator(
        [
            _generation("SELECT email FROM customers"),
            _generation("SELECT name FROM customers"),
        ]
    )

    result = answer("Show customers", generator, POLICY, object(), Settings())

    assert result.ok is True
    assert len(generator.calls) == 2
    assert generator.calls[1].previous[0].error_code == "COLUMN_NOT_ALLOWED"
    assert "not allowed" in generator.calls[1].previous[0].error_message
    assert [attempt.error_code for attempt in result.attempts] == [
        "COLUMN_NOT_ALLOWED",
        None,
    ]


def test_pipeline_stops_after_two_blocked_generations():
    generator = FakeGenerator(
        [
            _generation("SELECT email FROM customers"),
            _generation("SELECT phone FROM customers"),
        ]
    )

    result = answer("Show private data", generator, POLICY, object(), Settings())

    assert result.ok is False
    assert result.stage == "validator"
    assert result.error_code == "COLUMN_NOT_ALLOWED"
    assert len(generator.calls) == 2


def test_cannot_answer_does_not_run_sql(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("SQL must not run")

    monkeypatch.setattr("text_to_sql_guardrails.pipeline.run_readonly", fail_if_called)
    generator = FakeGenerator(
        [_generation(cannot_answer="The schema does not contain that data")]
    )

    result = answer("Unknown question", generator, POLICY, object(), Settings())

    assert result.ok is False
    assert result.stage == "model"
    assert result.error_code == "CANNOT_ANSWER"
    assert result.attempts == []


def test_refusal_becomes_a_model_stage_result():
    class RefusingGenerator:
        def generate(self, question, schema_prompt, previous):
            raise LlmRefused("The model refused to answer")

    result = answer("question", RefusingGenerator(), POLICY, object(), Settings())

    assert result.ok is False
    assert result.stage == "model"
    assert result.error_code == "REFUSED"


@pytest.mark.parametrize(
    "sql",
    ["DELETE FROM orders", "SELECT email FROM customers", "SELECT pg_sleep(10)"],
)
def test_malicious_model_output_never_reaches_database(sql):
    class FailIfUsedEngine:
        def connect(self):
            raise AssertionError("database must not be touched")

    generator = FakeGenerator([_generation(sql), _generation(sql)])

    result = answer("malicious", generator, POLICY, FailIfUsedEngine(), Settings())

    assert result.ok is False
    assert result.stage == "validator"
    assert len(generator.calls) == 2


def test_query_failed_is_retried_once(monkeypatch):
    calls = 0

    def run(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise QueryFailed("Database query failed")
        return _query_result()

    monkeypatch.setattr("text_to_sql_guardrails.pipeline.run_readonly", run)
    generator = FakeGenerator(
        [_generation("SELECT id FROM orders"), _generation("SELECT id FROM orders")]
    )

    result = answer("Show orders", generator, POLICY, object(), Settings())

    assert result.ok is True
    assert generator.calls[1].previous[0].error_code == "QUERY_FAILED"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (QueryPermissionDenied("denied"), "PERMISSION_DENIED"),
        (QueryTimeout("timed out"), "TIMEOUT"),
    ],
)
def test_guardrail_database_errors_are_not_retried(monkeypatch, error, code):
    def deny(*args, **kwargs):
        raise error

    monkeypatch.setattr("text_to_sql_guardrails.pipeline.run_readonly", deny)
    generator = FakeGenerator([_generation("SELECT id FROM orders")])

    result = answer("Show orders", generator, POLICY, object(), Settings())

    assert result.ok is False
    assert result.error_code == code
    assert len(generator.calls) == 1
