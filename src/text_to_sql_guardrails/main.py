"""HTTP API for policy inspection and guarded SQL execution."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from .config import resolve_policy_path, settings
from .db import get_readonly_engine
from .guard.executor import (
    QueryFailed,
    QueryPermissionDenied,
    QueryTimeout,
    run_readonly,
)
from .guard.policy import Policy, load_policy
from .guard.validator import validate
from .llm.anthropic_gen import AnthropicGenerator
from .llm.base import LlmFailed, LlmNotConfigured, SqlGenerator
from .pipeline import AskResult, answer

app = FastAPI(title="text-to-sql-guardrails")


@lru_cache
def get_policy() -> Policy:
    return load_policy(resolve_policy_path(settings.policy_path))


@lru_cache
def get_generator() -> SqlGenerator:
    return AnthropicGenerator(settings)


PolicyDep = Annotated[Policy, Depends(get_policy)]
EngineDep = Annotated[Engine, Depends(get_readonly_engine)]
GeneratorDep = Annotated[SqlGenerator, Depends(get_generator)]


class QueryIn(BaseModel):
    sql: str = Field(max_length=10_000)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1_000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/schema")
def schema(policy: PolicyDep) -> dict[str, dict[str, list[str]]]:
    return {
        "tables": {
            table: sorted(columns) for table, columns in sorted(policy.tables.items())
        }
    }


@app.post("/query")
def query(body: QueryIn, policy: PolicyDep, engine: EngineDep) -> dict[str, object]:
    validation = validate(body.sql, policy)
    if not validation.ok:
        return {
            "ok": False,
            "stage": "validator",
            "violations": [
                {"code": violation.code.value, "message": violation.message}
                for violation in validation.violations
            ],
        }

    assert validation.sql is not None
    try:
        result = run_readonly(
            validation.sql,
            engine,
            timeout_ms=settings.statement_timeout_ms,
            max_rows=policy.max_limit,
        )
    except QueryTimeout as error:
        return _database_error("TIMEOUT", str(error))
    except QueryPermissionDenied as error:
        return _database_error("PERMISSION_DENIED", str(error))
    except QueryFailed as error:
        return _database_error("QUERY_FAILED", str(error))

    return {
        "ok": True,
        "sql": validation.sql,
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "elapsed_ms": result.elapsed_ms,
    }


@app.post("/ask", response_model=None)
def ask(
    body: AskIn,
    policy: PolicyDep,
    engine: EngineDep,
    generator: GeneratorDep,
) -> dict[str, object] | JSONResponse:
    try:
        result = answer(body.question, generator, policy, engine, settings)
    except LlmNotConfigured as error:
        return _model_http_error(503, "LLM_NOT_CONFIGURED", str(error))
    except LlmFailed as error:
        return _model_http_error(502, "LLM_FAILED", str(error))
    return _ask_response(result)


def _ask_response(result: AskResult) -> dict[str, object]:
    attempts = [
        {"sql": attempt.sql, "error_code": attempt.error_code}
        for attempt in result.attempts
    ]
    if not result.ok:
        assert result.stage is not None
        assert result.error_code is not None
        assert result.error_message is not None
        return {
            "ok": False,
            "stage": result.stage,
            "error": {"code": result.error_code, "message": result.error_message},
            "attempts": attempts,
        }

    assert result.sql is not None
    assert result.query_result is not None
    assert result.model is not None
    query_result = result.query_result
    return {
        "ok": True,
        "question": result.question,
        "sql": result.sql,
        "columns": query_result.columns,
        "rows": query_result.rows,
        "row_count": query_result.row_count,
        "truncated": query_result.truncated,
        "elapsed_ms": query_result.elapsed_ms,
        "attempts": attempts,
        "model": result.model,
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        },
    }


def _model_http_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "stage": "model",
            "error": {"code": code, "message": message},
            "attempts": [],
        },
    )


def _database_error(code: str, message: str) -> dict[str, object]:
    return {
        "ok": False,
        "stage": "database",
        "error": {"code": code, "message": message},
    }
