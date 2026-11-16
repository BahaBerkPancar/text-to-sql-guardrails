"""Load and validate the SQL guardrail policy."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


def _name(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip().casefold()


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True)
class Policy:
    """The normalized allowlist and row limits used by the validator."""

    tables: Mapping[str, frozenset[str]]
    default_limit: int
    max_limit: int
    extra_functions: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        default_limit = _positive_int(self.default_limit, "default_limit")
        max_limit = _positive_int(self.max_limit, "max_limit")
        if default_limit > max_limit:
            raise ValueError("default_limit must not exceed max_limit")

        normalized_tables: dict[str, frozenset[str]] = {}
        for raw_table, raw_columns in self.tables.items():
            table = _name(raw_table, "table name")
            columns = frozenset(_name(column, f"column in {table}") for column in raw_columns)
            if not columns:
                raise ValueError(f"table {table!r} must allow at least one column")
            if table in normalized_tables:
                raise ValueError(f"duplicate table name after case folding: {table!r}")
            normalized_tables[table] = columns

        if not normalized_tables:
            raise ValueError("policy must allow at least one table")

        normalized_functions = frozenset(
            _name(function, "function name") for function in self.extra_functions
        )
        object.__setattr__(self, "tables", MappingProxyType(normalized_tables))
        object.__setattr__(self, "default_limit", default_limit)
        object.__setattr__(self, "max_limit", max_limit)
        object.__setattr__(self, "extra_functions", normalized_functions)


def load_policy(path: str | Path) -> Policy:
    """Load a TOML policy, rejecting missing or malformed sections."""

    with Path(path).open("rb") as policy_file:
        data = tomllib.load(policy_file)

    limits = data.get("limits")
    tables = data.get("tables")
    functions = data.get("functions")
    if not isinstance(limits, dict):
        raise TypeError("policy requires a [limits] table")
    if not isinstance(tables, dict):
        raise TypeError("policy requires a [tables] table")
    if not isinstance(functions, dict):
        raise TypeError("policy requires a [functions] table")

    raw_functions = functions.get("allowed")
    if not isinstance(raw_functions, list):
        raise TypeError("functions.allowed must be an array")

    normalized_tables: dict[str, frozenset[str]] = {}
    for table, columns in tables.items():
        if not isinstance(columns, list):
            raise TypeError(f"columns for table {table!r} must be an array")
        if any(not isinstance(column, str) for column in columns):
            raise TypeError(f"columns for table {table!r} must be strings")
        normalized_tables[table] = frozenset(columns)

    if any(not isinstance(function, str) for function in raw_functions):
        raise TypeError("functions.allowed entries must be strings")

    try:
        default_limit = limits["default_limit"]
        max_limit = limits["max_limit"]
    except KeyError as error:
        raise ValueError(f"missing limit: {error.args[0]}") from error

    return Policy(
        tables=normalized_tables,
        default_limit=default_limit,
        max_limit=max_limit,
        extra_functions=frozenset(raw_functions),
    )
