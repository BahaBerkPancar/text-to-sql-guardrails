from __future__ import annotations

from pathlib import Path

import pytest

from text_to_sql_guardrails.guard.policy import Policy, load_policy


def test_load_demo_policy() -> None:
    policy = load_policy("config/policy.toml")

    assert policy.default_limit == 100
    assert policy.max_limit == 500
    assert set(policy.tables) == {"customers", "products", "orders", "order_items"}
    assert policy.tables["customers"] == {"id", "name", "city", "country", "created_at"}
    assert "email" not in policy.tables["customers"]
    assert policy.extra_functions == frozenset()


def test_policy_normalizes_names_case_insensitively() -> None:
    policy = Policy(
        tables={"Customers": frozenset({"ID", "Name"})},
        default_limit=1,
        max_limit=2,
        extra_functions=frozenset({"My_Function"}),
    )

    assert policy.tables == {"customers": frozenset({"id", "name"})}
    assert policy.extra_functions == {"my_function"}


@pytest.mark.parametrize(
    "policy_text",
    [
        """
[limits]
default_limit = 0
max_limit = 10
[tables]
customers = ["id"]
[functions]
allowed = []
""",
        """
[limits]
default_limit = 20
max_limit = 10
[tables]
customers = ["id"]
[functions]
allowed = []
""",
        """
[limits]
default_limit = 1
max_limit = 10
[tables]
customers = []
[functions]
allowed = []
""",
        """
[limits]
default_limit = 1
max_limit = 10
[tables]
customers = [1]
[functions]
allowed = []
""",
    ],
)
def test_invalid_policy_is_rejected(tmp_path: Path, policy_text: str) -> None:
    path = tmp_path / "policy.toml"
    path.write_text(policy_text)

    with pytest.raises((TypeError, ValueError)):
        load_policy(path)
