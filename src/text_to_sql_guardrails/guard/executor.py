"""Execute validated SQL inside a short, read-only transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from time import perf_counter
from typing import Any

from psycopg import Error as PsycopgError
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError


class QueryError(Exception):
    """Base class for safe, user-facing database failures."""

    def __init__(self, message: str, *, sqlstate: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


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


def _safe_error(error: SQLAlchemyError | PsycopgError) -> QueryError:
    sqlstate = getattr(error, "sqlstate", None) or getattr(
        getattr(error, "orig", None), "sqlstate", None
    )
    if sqlstate == "57014":
        return QueryTimeout("Query exceeded the statement timeout", sqlstate=sqlstate)
    if sqlstate in {"25006", "42501"}:
        return QueryPermissionDenied(
            "Query was denied by the read-only database role", sqlstate=sqlstate
        )
    return QueryFailed("Database query failed", sqlstate=sqlstate)


def run_readonly(
    sql: str, engine: Engine, timeout_ms: int, max_rows: int
) -> QueryResult:
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
                driver_sql = sql
                if engine.dialect.paramstyle in {"format", "pyformat"}:
                    driver_sql = driver_sql.replace("%", "%%")
                dbapi_connection = connection.connection.driver_connection
                with dbapi_connection.cursor() as cursor:
                    # Prepared execution forces psycopg's extended protocol,
                    # which rejects multiple commands in one execute.
                    cursor.execute(driver_sql, {}, prepare=True)
                    columns = [column.name for column in cursor.description or []]
                    fetched = cursor.fetchmany(max_rows + 1)
                truncated = len(fetched) > max_rows
                rows = [
                    [_json_value(value) for value in row] for row in fetched[:max_rows]
                ]
            finally:
                if transaction.is_active:
                    transaction.rollback()
    except (DBAPIError, PsycopgError) as error:
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
