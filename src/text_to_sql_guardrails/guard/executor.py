"""Execute validated SQL inside a short, read-only transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from time import perf_counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError


class QueryError(Exception):
    """Base class for safe, user-facing database failures."""


class QueryTimeout(QueryError):
    pass


class QueryPermissionDenied(QueryError):
    pass


class QueryFailed(QueryError):
    pass


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _safe_error(error: SQLAlchemyError) -> QueryError:
    sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
    if sqlstate == "57014":
        return QueryTimeout("Query exceeded the statement timeout")
    if sqlstate in {"25006", "42501"}:
        return QueryPermissionDenied("Query was denied by the read-only database role")
    return QueryFailed("Database query failed")


def run_readonly(sql: str, engine: Engine, timeout_ms: int, max_rows: int) -> QueryResult:
    """Run SQL with transaction, timeout, and result-size safeguards."""

    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    if max_rows <= 0:
        raise ValueError("max_rows must be positive")

    started = perf_counter()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(
                    text("SELECT set_config('statement_timeout', :timeout, true)"),
                    {"timeout": f"{timeout_ms}ms"},
                )
                result = connection.execute(text(sql))
                columns = list(result.keys())
                fetched = result.fetchmany(max_rows + 1)
                truncated = len(fetched) > max_rows
                rows = [
                    [_json_value(value) for value in row]
                    for row in fetched[:max_rows]
                ]
            finally:
                if transaction.is_active:
                    transaction.rollback()
    except DBAPIError as error:
        raise _safe_error(error) from None
    except SQLAlchemyError:
        raise QueryFailed("Database query failed") from None

    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        elapsed_ms=round((perf_counter() - started) * 1_000, 3),
    )
