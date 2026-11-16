from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import text

from text_to_sql_guardrails.seed import seed_database

pytestmark = pytest.mark.pg


def _checksum(engine) -> str:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT o.id, o.customer_id, o.status, o.ordered_at, o.total, "
                "oi.product_id, oi.quantity, oi.unit_price "
                "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
                "ORDER BY o.id, oi.id"
            )
        )
        payload = "\n".join("|".join(map(str, row)) for row in rows)
    return hashlib.sha256(payload.encode()).hexdigest()


def test_seed_is_deterministic_and_idempotent(pg_engines):
    admin_engine, _ = pg_engines
    first = _checksum(admin_engine)

    seed_database(admin_engine)
    second = _checksum(admin_engine)

    assert second == first
