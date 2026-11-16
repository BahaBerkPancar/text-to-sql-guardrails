"""HTTP API for policy inspection and guarded SQL execution."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from .config import settings
from .db import get_readonly_engine
from .guard.executor import (
    QueryFailed,
    QueryPermissionDenied,
    QueryTimeout,
    run_readonly,
)
from .guard.policy import Policy, load_policy
from .guard.validator import validate

app = FastAPI(title="text-to-sql-guardrails")


@lru_cache
def get_policy() -> Policy:
    return load_policy(settings.policy_path)


PolicyDep = Annotated[Policy, Depends(get_policy)]
EngineDep = Annotated[Engine, Depends(get_readonly_engine)]


class QueryIn(BaseModel):
    sql: str = Field(max_length=10_000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/schema")
def schema(policy: PolicyDep) -> dict[str, dict[str, list[str]]]:
    return {
        "tables": {
            table: sorted(columns)
            for table, columns in sorted(policy.tables.items())
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


def _database_error(code: str, message: str) -> dict[str, object]:
    return {
        "ok": False,
        "stage": "database",
        "error": {"code": code, "message": message},
    }
