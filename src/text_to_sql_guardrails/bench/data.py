"""Load and validate the benchmark's version-controlled YAML corpus."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

QUESTION_CATEGORIES = frozenset(
    {
        "simple",
        "filter",
        "join",
        "aggregate",
        "group_having",
        "date",
        "window",
        "cte",
        "subquery",
        "set_op",
    }
)
DIFFICULTIES = frozenset({"easy", "medium", "hard"})
ATTACK_CATEGORIES = frozenset(
    {
        "write",
        "ddl",
        "stacked",
        "comment_trick",
        "denied_column",
        "denied_table",
        "system_catalog",
        "whole_row",
        "dangerous_function",
        "limit_escape",
        "dos",
        "encoding",
    }
)
MIN_QUESTIONS = 40
MIN_ATTACKS = 100
MIN_ATTACKS_PER_CATEGORY = 5
ATTACK_PROMPT_CATEGORIES = frozenset(
    {
        "denied_data",
        "write_request",
        "schema_probe",
        "prompt_injection",
        "multi_step",
        "exfiltration",
        "dos",
    }
)
MIN_ATTACK_PROMPTS = 30
MIN_ATTACK_PROMPT_CATEGORIES = 6


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    gold_sql: str
    category: str
    difficulty: str


@dataclass(frozen=True)
class Attack:
    id: str
    sql: str
    category: str
    note: str
    allowed_to_pass: str | None = None


@dataclass(frozen=True)
class AttackPrompt:
    id: str
    question: str
    category: str
    note: str


def _load_rows(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as source:
        data = yaml.safe_load(source)
    if not isinstance(data, list):
        raise TypeError(f"{path} must contain a YAML list")
    if any(not isinstance(row, dict) for row in data):
        raise ValueError(f"every entry in {path} must be a mapping")
    return data


def _required_text(row: dict[str, Any], field: str, kind: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{kind} {field!r} must be a non-empty string")
    return value.strip()


def _unique_ids(
    rows: list[Question] | list[Attack] | list[AttackPrompt], kind: str
) -> None:
    ids = [row.id for row in rows]
    duplicates = sorted({row_id for row_id in ids if ids.count(row_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate {kind} ids: {', '.join(duplicates)}")


def load_questions(path: str | Path, *, enforce_minimums: bool = True) -> list[Question]:
    questions: list[Question] = []
    for row in _load_rows(path):
        category = _required_text(row, "category", "question")
        difficulty = _required_text(row, "difficulty", "question")
        if category not in QUESTION_CATEGORIES:
            raise ValueError(f"unknown question category: {category}")
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"unknown question difficulty: {difficulty}")
        questions.append(
            Question(
                id=_required_text(row, "id", "question"),
                question=_required_text(row, "question", "question"),
                gold_sql=_required_text(row, "gold_sql", "question"),
                category=category,
                difficulty=difficulty,
            )
        )
    _unique_ids(questions, "question")
    if enforce_minimums and len(questions) < MIN_QUESTIONS:
        raise ValueError(f"questions corpus requires at least {MIN_QUESTIONS} entries")
    missing = QUESTION_CATEGORIES.difference(question.category for question in questions)
    if enforce_minimums and missing:
        raise ValueError(f"questions corpus is missing categories: {', '.join(sorted(missing))}")
    return questions


def load_attacks(path: str | Path, *, enforce_minimums: bool = True) -> list[Attack]:
    attacks: list[Attack] = []
    for row in _load_rows(path):
        category = _required_text(row, "category", "attack")
        if category not in ATTACK_CATEGORIES:
            raise ValueError(f"unknown attack category: {category}")
        allowed = row.get("allowed_to_pass")
        if allowed is not None and (not isinstance(allowed, str) or not allowed.strip()):
            raise ValueError("attack allowed_to_pass must be a non-empty reason")
        attacks.append(
            Attack(
                id=_required_text(row, "id", "attack"),
                sql=_required_text(row, "sql", "attack"),
                category=category,
                note=_required_text(row, "note", "attack"),
                allowed_to_pass=allowed.strip() if isinstance(allowed, str) else None,
            )
        )
    _unique_ids(attacks, "attack")
    if enforce_minimums and len(attacks) < MIN_ATTACKS:
        raise ValueError(f"attacks corpus requires at least {MIN_ATTACKS} entries")
    if enforce_minimums:
        counts = {
            category: sum(attack.category == category for attack in attacks)
            for category in ATTACK_CATEGORIES
        }
        undersized = {
            category: count
            for category, count in counts.items()
            if count < MIN_ATTACKS_PER_CATEGORY
        }
        if undersized:
            detail = ", ".join(
                f"{category}={count}" for category, count in sorted(undersized.items())
            )
            raise ValueError(
                f"attack categories require at least {MIN_ATTACKS_PER_CATEGORY}: {detail}"
            )
    return attacks


def load_attack_prompts(
    path: str | Path, *, enforce_minimums: bool = True
) -> list[AttackPrompt]:
    prompts: list[AttackPrompt] = []
    for row in _load_rows(path):
        category = _required_text(row, "category", "attack prompt")
        if category not in ATTACK_PROMPT_CATEGORIES:
            raise ValueError(f"unknown attack prompt category: {category}")
        prompts.append(
            AttackPrompt(
                id=_required_text(row, "id", "attack prompt"),
                question=_required_text(row, "question", "attack prompt"),
                category=category,
                note=_required_text(row, "note", "attack prompt"),
            )
        )
    _unique_ids(prompts, "attack prompt")
    if enforce_minimums and len(prompts) < MIN_ATTACK_PROMPTS:
        raise ValueError(
            f"attack prompt corpus requires at least {MIN_ATTACK_PROMPTS} entries"
        )
    categories = {prompt.category for prompt in prompts}
    if enforce_minimums and len(categories) < MIN_ATTACK_PROMPT_CATEGORIES:
        raise ValueError(
            "attack prompt corpus requires at least "
            f"{MIN_ATTACK_PROMPT_CATEGORIES} categories"
        )
    return prompts
