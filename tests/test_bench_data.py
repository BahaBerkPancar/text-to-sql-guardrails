from __future__ import annotations

from collections import Counter

import pytest

from text_to_sql_guardrails.bench.data import (
    ATTACK_CATEGORIES,
    MIN_ATTACKS,
    MIN_ATTACKS_PER_CATEGORY,
    MIN_QUESTIONS,
    QUESTION_CATEGORIES,
    load_attacks,
    load_questions,
)
from text_to_sql_guardrails.guard.policy import load_policy
from text_to_sql_guardrails.guard.validator import validate


def test_versioned_benchmark_corpora_meet_the_contract() -> None:
    attacks = load_attacks("bench/attacks.yaml")
    questions = load_questions("bench/questions.yaml")

    assert len(attacks) >= MIN_ATTACKS
    assert len(questions) >= MIN_QUESTIONS
    assert set(Counter(attack.category for attack in attacks)) == ATTACK_CATEGORIES
    assert all(
        count >= MIN_ATTACKS_PER_CATEGORY
        for count in Counter(attack.category for attack in attacks).values()
    )
    assert {question.category for question in questions} == QUESTION_CATEGORIES


def test_every_gold_query_passes_static_validation() -> None:
    policy = load_policy("config/policy.toml")

    for question in load_questions("bench/questions.yaml"):
        result = validate(question.gold_sql, policy)
        assert result.ok, (question.id, result.violations)


def test_loader_rejects_duplicate_ids(tmp_path) -> None:
    path = tmp_path / "questions.yaml"
    path.write_text(
        """
- id: duplicate
  question: First
  gold_sql: SELECT 1 ORDER BY 1
  category: simple
  difficulty: easy
- id: duplicate
  question: Second
  gold_sql: SELECT 2 ORDER BY 1
  category: simple
  difficulty: easy
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate question ids"):
        load_questions(path, enforce_minimums=False)


def test_loader_rejects_missing_required_field(tmp_path) -> None:
    path = tmp_path / "attacks.yaml"
    path.write_text(
        """
- id: missing-note
  sql: SELECT 1
  category: encoding
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="note"):
        load_attacks(path, enforce_minimums=False)


def test_allowed_pass_requires_a_reason(tmp_path) -> None:
    path = tmp_path / "attacks.yaml"
    path.write_text(
        """
- id: no-reason
  sql: SELECT 1
  category: encoding
  note: harmless literal
  allowed_to_pass: true
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-empty reason"):
        load_attacks(path, enforce_minimums=False)
