from types import SimpleNamespace
from unittest.mock import Mock

import anthropic
import httpx2
import pytest

from text_to_sql_guardrails.config import Settings
from text_to_sql_guardrails.llm.anthropic_gen import AnthropicGenerator
from text_to_sql_guardrails.llm.base import (
    Attempt,
    LlmFailed,
    LlmNotConfigured,
    LlmRefused,
)
from text_to_sql_guardrails.llm.prompt import SYSTEM_PROMPT


def _response(
    payload: str = '{"sql":"SELECT id FROM orders","cannot_answer":""}',
    *,
    stop_reason: str = "end_turn",
):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=payload)],
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=12, output_tokens=7),
    )


def _client(response=None, error=None):
    create = (
        Mock(side_effect=error) if error else Mock(return_value=response or _response())
    )
    client = SimpleNamespace(
        beta=SimpleNamespace(messages=SimpleNamespace(create=create))
    )
    return client, create


def _status_error(error_type, status_code):
    request = httpx2.Request("POST", "https://api.example.test/messages")
    response = httpx2.Response(status_code, request=request)
    return error_type("redacted test error", response=response, body=None)


def test_builds_current_structured_output_request_and_parses_response():
    client, create = _client()
    generator = AnthropicGenerator(Settings(), client=client)
    previous = [
        Attempt("SELECT missing FROM orders", "COLUMN_NOT_ALLOWED", "not allowed")
    ]

    result = generator.generate("Show orders", "SCHEMA", previous)

    assert result.sql == "SELECT id FROM orders"
    assert result.cannot_answer is None
    assert result.input_tokens == 12
    assert result.output_tokens == 7
    kwargs = create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["max_tokens"] == 4000
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["fallbacks"] == "default"
    assert kwargs["cache_control"] == {"type": "ephemeral"}
    assert kwargs["system"] == SYSTEM_PROMPT + "\n\nSCHEMA"
    assert kwargs["output_config"]["effort"] == "medium"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert kwargs["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert kwargs["messages"][0] == {"role": "user", "content": "Show orders"}
    assert kwargs["messages"][1]["role"] == "assistant"
    assert "COLUMN_NOT_ALLOWED" in kwargs["messages"][2]["content"]


@pytest.mark.parametrize(
    ("stop_reason", "error_type"),
    [("refusal", LlmRefused), ("max_tokens", LlmFailed)],
)
def test_maps_non_success_stop_reasons(stop_reason, error_type):
    client, _ = _client(_response(stop_reason=stop_reason))

    with pytest.raises(error_type):
        AnthropicGenerator(Settings(), client=client).generate("q", "schema", [])


@pytest.mark.parametrize(
    ("sdk_error", "expected"),
    [
        (_status_error(anthropic.AuthenticationError, 401), LlmNotConfigured),
        (_status_error(anthropic.RateLimitError, 429), LlmFailed),
    ],
)
def test_maps_sdk_errors_without_exposing_provider_messages(sdk_error, expected):
    client, _ = _client(error=sdk_error)

    with pytest.raises(expected) as caught:
        AnthropicGenerator(Settings(), client=client).generate("q", "schema", [])

    assert "redacted test error" not in str(caught.value)


def test_client_is_lazy_and_missing_credentials_are_mapped(monkeypatch):
    constructor = Mock(side_effect=anthropic.AnthropicError("missing credentials"))
    monkeypatch.setattr(anthropic, "Anthropic", constructor)
    generator = AnthropicGenerator(Settings())

    assert constructor.call_count == 0
    with pytest.raises(LlmNotConfigured):
        generator.generate("q", "schema", [])
    constructor.assert_called_once_with(timeout=60, max_retries=2)
