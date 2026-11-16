from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from text_to_sql_guardrails.guard.policy import load_policy
from text_to_sql_guardrails.guard.roles import apply_role
from text_to_sql_guardrails.main import app
from text_to_sql_guardrails.seed import seed_database

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def pg_engines() -> Iterator[tuple[Engine, Engine]]:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not set")

    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    seed_database(admin_engine)

    role = "t2s_readonly_test"
    password = "t2s-readonly-test-password"
    apply_role(admin_engine, load_policy(ROOT / "config/policy.toml"), role, password)
    readonly_url = make_url(database_url).set(username=role, password=password)
    readonly_engine = create_engine(readonly_url)

    yield admin_engine, readonly_engine

    readonly_engine.dispose()
    admin_engine.dispose()
