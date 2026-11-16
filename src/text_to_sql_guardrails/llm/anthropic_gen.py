"""Anthropic structured-output adapter."""

from __future__ import annotations

import json
from typing import Any

import anthropic

from text_to_sql_guardrails.config import Settings

from .base import Attempt, Generation, LlmFailed, LlmNotConfigured, LlmRefused
from .prompt import SYSTEM_PROMPT

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string"},
        "cannot_answer": {"type": "string"},
    },
    "required": ["sql", "cannot_answer"],
    "additionalProperties": False,
}


class AnthropicGenerator:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                self._client = anthropic.Anthropic(
                    timeout=self._settings.llm_timeout_s,
                    max_retries=2,
                )
            except anthropic.AnthropicError:
                raise LlmNotConfigured(
                    "Anthropic credentials are not configured"
                ) from None
        return self._client

    def generate(
        self,
        question: str,
        schema_prompt: str,
        previous: list[Attempt],
    ) -> Generation:
        messages: list[dict[str, str]] = [{"role": "user", "content": question}]
        for attempt in previous:
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {"sql": attempt.sql, "cannot_answer": ""},
                            separators=(",", ":"),
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "The SQL was rejected. Correct it without changing the question.\n"
                            f"Error code: {attempt.error_code}\n"
                            f"Error message: {attempt.error_message}"
                        ),
                    },
                ]
            )

        try:
            response = self._get_client().beta.messages.create(
                model=self._settings.llm_model,
                max_tokens=4000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                cache_control={"type": "ephemeral"},
                system=SYSTEM_PROMPT + "\n\n" + schema_prompt,
                output_config={
                    "effort": self._settings.llm_effort,
                    "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA},
                },
                messages=messages,
            )
        except anthropic.AuthenticationError:
            raise LlmNotConfigured("Anthropic credentials are not configured") from None
        except TypeError as error:
            # The SDK builds a client without credentials and raises this TypeError
            # ("Could not resolve authentication method") only when a request is made.
            if "authentication" not in str(error).lower():
                raise
            raise LlmNotConfigured("Anthropic credentials are not configured") from None
        except anthropic.RateLimitError:
            raise LlmFailed("Anthropic rate limit exceeded") from None
        except anthropic.APIStatusError:
            raise LlmFailed("Anthropic request failed") from None
        except anthropic.APIConnectionError:
            raise LlmFailed("Could not connect to Anthropic") from None

        if response.stop_reason == "refusal":
            raise LlmRefused("The model refused to answer")
        if response.stop_reason == "max_tokens":
            raise LlmFailed("The model response exceeded the token limit")

        text = next(
            (
                block.text
                for block in response.content
                if getattr(block, "type", None) == "text"
            ),
            None,
        )
        if not text:
            raise LlmFailed("The model returned no structured response")
        try:
            payload = json.loads(text)
            sql_value = payload["sql"]
            cannot_answer_value = payload["cannot_answer"]
        except (json.JSONDecodeError, KeyError, TypeError):
            raise LlmFailed(
                "The model returned an invalid structured response"
            ) from None
        if not isinstance(sql_value, str) or not isinstance(cannot_answer_value, str):
            raise LlmFailed("The model returned an invalid structured response")

        sql = sql_value.strip() or None
        cannot_answer = cannot_answer_value.strip() or None
        if (sql is None) == (cannot_answer is None):
            raise LlmFailed(
                "The model response must contain either SQL or cannot_answer"
            )

        return Generation(
            sql=sql,
            cannot_answer=cannot_answer,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_input_tokens=(
                getattr(response.usage, "cache_read_input_tokens", None) or 0
            ),
            cache_creation_input_tokens=(
                getattr(response.usage, "cache_creation_input_tokens", None) or 0
            ),
        )
