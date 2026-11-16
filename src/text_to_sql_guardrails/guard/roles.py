"""Create and constrain the database identity used for generated SQL."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .policy import Policy


def _identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("database identifiers must be non-empty and contain no NUL bytes")
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _literal(value: str) -> str:
    if "\x00" in value:
        raise ValueError("database strings must contain no NUL bytes")
    return "'" + value.replace("'", "''") + "'"


def grant_statements(policy: Policy, role: str) -> list[str]:
    """Return the complete, deterministic privilege configuration for ``role``."""

    quoted_role = _identifier(role)
    statements = [
        f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {quoted_role}",
        f"GRANT USAGE ON SCHEMA public TO {quoted_role}",
    ]
    for table, columns in sorted(policy.tables.items()):
        quoted_columns = ", ".join(_identifier(column) for column in sorted(columns))
        statements.append(
            f"GRANT SELECT ({quoted_columns}) ON TABLE "
            f'{_identifier("public")}.{_identifier(table)} TO {quoted_role}'
        )
    statements.extend(
        [
            f"ALTER ROLE {quoted_role} SET default_transaction_read_only = on",
            f"ALTER ROLE {quoted_role} SET statement_timeout = '3000ms'",
        ]
    )
    return statements


def apply_role(admin_engine: Engine, policy: Policy, role: str, password: str) -> None:
    """Create or update a LOGIN role, then replace its table privileges."""

    quoted_role = _identifier(role)
    quoted_password = _literal(password)
    with admin_engine.begin() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
        ).scalar_one_or_none()
        if exists:
            connection.execute(text(f"ALTER ROLE {quoted_role} LOGIN PASSWORD {quoted_password}"))
        else:
            connection.execute(text(f"CREATE ROLE {quoted_role} LOGIN PASSWORD {quoted_password}"))
        for statement in grant_statements(policy, role):
            connection.execute(text(statement))
