from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


def create_readonly_engine(database_url: str | URL, **kwargs: Any) -> Engine:
    """Create an engine that discards all session state at every pool check-in."""

    engine = create_engine(database_url, **kwargs)

    @event.listens_for(engine, "checkin")
    def discard_session_state(
        dbapi_connection: Any, _connection_record: Any
    ) -> None:
        if dbapi_connection is None:
            return
        previous_autocommit = dbapi_connection.autocommit
        try:
            dbapi_connection.rollback()
            dbapi_connection.autocommit = True
            with dbapi_connection.cursor() as cursor:
                cursor.execute("DISCARD ALL")
        finally:
            dbapi_connection.autocommit = previous_autocommit

    return engine


readonly_engine = create_readonly_engine(settings.readonly_database_url)


def get_readonly_engine() -> Engine:
    """FastAPI dependency for the database identity used to execute queries."""

    return readonly_engine
