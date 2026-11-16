"""Shared types for SQL generation providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LlmError(Exception):
    """Base class for safe, user-facing model failures."""


class LlmNotConfigured(LlmError):
    pass


class LlmFailed(LlmError):
    pass


class LlmRefused(LlmError):
    pass


@dataclass(frozen=True)
class Attempt:
    sql: str
    error_code: str
    error_message: str


@dataclass(frozen=True)
class Generation:
    sql: str | None
    cannot_answer: str | None
    model: str
    input_tokens: int
    output_tokens: int


class SqlGenerator(Protocol):
    def generate(
        self,
        question: str,
        schema_prompt: str,
        previous: list[Attempt],
    ) -> Generation:
        """Generate one SQL candidate or explain why the question cannot be answered."""

        ...
