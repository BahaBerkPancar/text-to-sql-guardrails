from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from text_to_sql_guardrails import models  # noqa: F401
from text_to_sql_guardrails.db import Base

ROOT = Path(__file__).resolve().parents[1]


def test_migrations_match_models(tmp_path):
    """Fails when a model changes without a new Alembic migration."""
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    with create_engine(url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
