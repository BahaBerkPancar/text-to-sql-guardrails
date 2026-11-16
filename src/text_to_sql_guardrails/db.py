from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


readonly_engine = create_engine(settings.readonly_database_url)


def get_readonly_engine() -> Engine:
    """FastAPI dependency for the database identity used to execute queries."""

    return readonly_engine
