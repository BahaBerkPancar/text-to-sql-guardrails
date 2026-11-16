from __future__ import annotations

from decimal import Decimal

import pytest

from text_to_sql_guardrails.bench.data import load_attack_prompts
from text_to_sql_guardrails.bench.guardrails import cli
from text_to_sql_guardrails.bench.llm import (
    estimate_run_cost,
    generation_cost,
    load_prices,
    outermost_has_order_by,
    result_rows_equal,
)
from text_to_sql_guardrails.llm.base import Generation


def test_attack_prompt_corpus_is_large_varied_and_unique() -> None:
    prompts = load_attack_prompts("bench/attack_prompts.yaml")

    assert len(prompts) >= 30
    assert len({prompt.id for prompt in prompts}) == len(prompts)
    assert len({prompt.category for prompt in prompts}) >= 6


def test_attack_prompt_loader_rejects_duplicates(tmp_path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "- {id: same, question: one, category: dos, note: n}\n"
        "- {id: same, question: two, category: dos, note: n}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate attack prompt ids"):
        load_attack_prompts(path, enforce_minimums=False)


def test_result_comparison_obeys_order_tolerance_and_ignores_column_names() -> None:
    expected = [[1, Decimal("10.000")], [2, Decimal("20.000")]]
    reversed_close = [[2, Decimal("20.009")], [1, Decimal("10.001")]]

    assert result_rows_equal(expected, reversed_close, ordered=False)
    assert not result_rows_equal(expected, reversed_close, ordered=True)
    assert not result_rows_equal(expected, [[1, 10], [2, 20.02]], ordered=False)
    assert outermost_has_order_by("SELECT id FROM orders ORDER BY id")
    assert not outermost_has_order_by(
        "SELECT * FROM (SELECT id FROM orders ORDER BY id) AS ordered_orders"
    )


def test_cost_math_includes_cache_rates_and_unknown_model_is_null() -> None:
    prices = load_prices("config/prices.toml")
    generation = Generation(
        "SELECT 1", None, "claude-haiku-5-5", 1_000_000, 1_000_000, 1_000_000, 1_000_000
    )

    assert generation_cost(generation, prices) == Decimal("0.735")
    assert (
        generation_cost(Generation("SELECT 1", None, "unknown", 1, 1), prices) is None
    )
    assert estimate_run_cost("unknown", "abcd", ["efgh"], prices)["cost_usd"] is None


def test_estimate_mode_does_not_construct_or_call_generator(
    monkeypatch, capsys
) -> None:
    class FailIfConstructed:
        def __init__(self, *args, **kwargs):
            raise AssertionError("generator must not be constructed")

    monkeypatch.setattr(
        "text_to_sql_guardrails.llm.anthropic_gen.AnthropicGenerator",
        FailIfConstructed,
    )

    result = cli(
        [
            "--mode",
            "llm",
            "--model",
            "claude-haiku-5-5",
            "--effort",
            "low",
        ]
    )

    assert result == 0
    assert "no model API call was made" in capsys.readouterr().out
