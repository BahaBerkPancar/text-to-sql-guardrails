from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
