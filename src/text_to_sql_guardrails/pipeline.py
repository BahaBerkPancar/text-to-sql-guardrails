"""Generate, validate, and execute an answer with one guarded repair attempt."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.engine import Engine

from .config import Settings
from .guard.executor import (
    QueryFailed,
    QueryPermissionDenied,
    QueryResult,
    QueryTimeout,
    run_readonly,
)
from .guard.policy import Policy
from .guard.validator import validate
from .llm.base import Attempt, LlmRefused, SqlGenerator
from .llm.prompt import build_schema_prompt


@dataclass(frozen=True)
class AskAttempt:
    sql: str
    error_code: str | None


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class AskResult:
    ok: bool
    question: str
    attempts: list[AskAttempt]
    model: str | None = None
    usage: Usage = field(default_factory=Usage)
    sql: str | None = None
    query_result: QueryResult | None = None
    stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def _failed(
    question: str,
    attempts: list[AskAttempt],
    stage: str,
    code: str,
    message: str,
    model: str | None,
    usage: Usage,
) -> AskResult:
    return AskResult(
        ok=False,
        question=question,
        attempts=attempts,
        model=model,
        usage=usage,
        stage=stage,
        error_code=code,
        error_message=message,
    )


def answer(
    question: str,
    generator: SqlGenerator,
    policy: Policy,
    engine: Engine,
    settings: Settings,
) -> AskResult:
    """Answer a question while treating every generated SQL string as untrusted."""

    previous: list[Attempt] = []
    attempts: list[AskAttempt] = []
    schema_prompt = build_schema_prompt(policy)
    model: str | None = None
    input_tokens = 0
    output_tokens = 0

    for call_number in range(2):
        try:
            generation = generator.generate(question, schema_prompt, previous)
        except LlmRefused as error:
            return _failed(
                question,
                attempts,
                "model",
                "REFUSED",
                str(error),
                model,
                Usage(input_tokens, output_tokens),
            )

        model = generation.model
        input_tokens += generation.input_tokens
        output_tokens += generation.output_tokens
        usage = Usage(input_tokens, output_tokens)
        if generation.cannot_answer is not None:
            return _failed(
                question,
                attempts,
                "model",
                "CANNOT_ANSWER",
                generation.cannot_answer,
                model,
                usage,
            )
        if generation.sql is None:
            return _failed(
                question,
                attempts,
                "model",
                "CANNOT_ANSWER",
                "The model did not provide SQL",
                model,
                usage,
            )

        sql = generation.sql
        validation = validate(sql, policy)
        if not validation.ok:
            first = validation.violations[0]
            message = "; ".join(
                violation.message for violation in validation.violations
            )
            previous.append(Attempt(sql, first.code.value, message))
            attempts.append(AskAttempt(sql, first.code.value))
            if call_number == 0:
                continue
            return _failed(
                question,
                attempts,
                "validator",
                first.code.value,
                message,
                model,
                usage,
            )

        assert validation.sql is not None
        try:
            query_result = run_readonly(
                validation.sql,
                engine,
                timeout_ms=settings.statement_timeout_ms,
                max_rows=policy.max_limit,
            )
        except QueryFailed as error:
            previous.append(Attempt(sql, "QUERY_FAILED", str(error)))
            attempts.append(AskAttempt(sql, "QUERY_FAILED"))
            if call_number == 0:
                continue
            return _failed(
                question,
                attempts,
                "database",
                "QUERY_FAILED",
                str(error),
                model,
                usage,
            )
        except QueryPermissionDenied as error:
            attempts.append(AskAttempt(sql, "PERMISSION_DENIED"))
            return _failed(
                question,
                attempts,
                "database",
                "PERMISSION_DENIED",
                str(error),
                model,
                usage,
            )
        except QueryTimeout as error:
            attempts.append(AskAttempt(sql, "TIMEOUT"))
            return _failed(
                question,
                attempts,
                "database",
                "TIMEOUT",
                str(error),
                model,
                usage,
            )

        attempts.append(AskAttempt(sql, None))
        return AskResult(
            ok=True,
            question=question,
            attempts=attempts,
            model=model,
            usage=usage,
            sql=validation.sql,
            query_result=query_result,
        )

    raise AssertionError("generation loop exited unexpectedly")
