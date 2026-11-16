from __future__ import annotations

import copy
import json

import pytest

from text_to_sql_guardrails.bench.data import load_attacks, load_questions
from text_to_sql_guardrails.bench.guardrails import (
    check_failures,
    run_benchmark,
    write_results,
)
from text_to_sql_guardrails.guard.policy import load_policy

pytestmark = pytest.mark.pg


def test_small_benchmark_writes_report_and_harm_trips_check(pg_engines, tmp_path) -> None:
    admin_engine, readonly_engine = pg_engines
    attack_ids = {"write_delete", "column_email", "comment_line_drop"}
    question_ids = {"q001", "q005"}
    attacks = [
        attack
        for attack in load_attacks("bench/attacks.yaml")
        if attack.id in attack_ids
    ]
    questions = [
        question
        for question in load_questions("bench/questions.yaml")
        if question.id in question_ids
    ]

    report = run_benchmark(
        admin_engine,
        readonly_engine,
        load_policy("config/policy.toml"),
        attacks,
        questions,
        timeout_ms=500,
    )
    json_path, markdown_path = write_results(report, tmp_path)

    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    assert persisted["mode"] == "guardrails"
    assert set(persisted["versions"]) == {
        "python",
        "postgresql",
        "sqlglot",
        "pyyaml",
    }
    assert persisted["metrics"]["layers"]["full"]["total"] == 3
    assert persisted["write_check"]["changed"] is False
    assert any(
        key.startswith("sequence:")
        for key in persisted["write_check"]["before"]
    )
    assert markdown_path.read_text(encoding="utf-8").startswith("# Guardrail benchmark")
    assert check_failures(report) == []

    harmful = copy.deepcopy(report)
    harmful["attacks"][0]["configurations"]["full"] = {
        "outcome": "passed",
        "violations": [],
        "leak": True,
        "write": False,
    }
    assert "harmful full-stack pass: write_delete" in check_failures(harmful)
