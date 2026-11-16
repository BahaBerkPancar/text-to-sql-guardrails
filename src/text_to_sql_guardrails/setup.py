"""Bootstrap the demo database and its restricted query role."""

from __future__ import annotations

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select

from .config import settings
from .guard.policy import load_policy
from .guard.roles import apply_role
from .models import Customer
from .seed import seed_database

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reseed", action="store_true", help="replace existing demo data")
    args = parser.parse_args()

    alembic_config = Config(str(ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(ROOT / "migrations"))
    alembic_config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(alembic_config, "head")

    admin_engine = create_engine(settings.database_url)
    with admin_engine.connect() as connection:
        customer_count = connection.scalar(select(func.count()).select_from(Customer))
    if args.reseed or customer_count == 0:
        seed_database(admin_engine)

    policy = load_policy(ROOT / settings.policy_path)
    apply_role(
        admin_engine,
        policy,
        settings.readonly_role,
        settings.readonly_password,
    )
    admin_engine.dispose()
