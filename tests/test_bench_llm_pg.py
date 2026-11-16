from __future__ import annotations

import pytest

from text_to_sql_guardrails.bench.data import load_attack_prompts, load_questions
from text_to_sql_guardrails.bench.llm import (
    GoldSqlGenerator,
    load_prices,
    run_benchmark,
)
from text_to_sql_guardrails.guard.policy import load_policy
from text_to_sql_guardrails.llm.base import Generation

pytestmark = pytest.mark.pg


def test_fake_subset_runs_through_pipeline_offline(pg_engines) -> None:
    admin_engine, readonly_engine = pg_engines
    questions = load_questions("bench/questions.yaml")[:3]
    attacks = load_attack_prompts("bench/attack_prompts.yaml")[:3]
    report = run_benchmark(
        admin_engine,
        readonly_engine,
        load_policy("config/policy.toml"),
        questions,
        attacks,
        GoldSqlGenerator(questions, "fake-model"),
        load_prices("config/prices.toml"),
        model="fake-model",
        effort="low",
        fake=True,
    )

    assert report["fake"] is True
    assert report["metrics"]["execution_accuracy"]["overall"]["correct"] == 3
    assert report["metrics"]["attacks"]["outcomes"] == {"declined": 3}
    assert report["metrics"]["attacks"]["harmful"] == 0


def test_malicious_generator_outputs_are_blocked(pg_engines) -> None:
    admin_engine, readonly_engine = pg_engines
    attacks = load_attack_prompts("bench/attack_prompts.yaml")[:3]
    scripts = {
        attacks[0].question: "SELECT email FROM customers",
        attacks[1].question: "DELETE FROM orders",
        attacks[2].question: "SELECT customers FROM customers ORDER BY email",
    }

    class MaliciousGenerator:
        def generate(self, question, schema_prompt, previous):
            del schema_prompt, previous
            return Generation(scripts[question], None, "malicious", 1, 1)

    report = run_benchmark(
        admin_engine,
        readonly_engine,
        load_policy("config/policy.toml"),
        [],
        attacks,
        MaliciousGenerator(),
        load_prices("config/prices.toml"),
        model="malicious",
        effort="low",
    )

    assert [row["outcome"] for row in report["attacks"]] == [
        "blocked_validator",
        "blocked_validator",
        "blocked_validator",
    ]
    assert report["metrics"]["attacks"]["harmful"] == 0
    assert report["write_check"]["changed"] is False
