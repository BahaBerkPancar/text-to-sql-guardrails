from __future__ import annotations

from text_to_sql_guardrails.bench.guardrails import (
    SensitiveValues,
    check_failures,
    compute_metrics,
    leaked,
)


def _configuration(outcome: str, *, leak: bool = False, write: bool = False):
    return {"outcome": outcome, "leak": leak, "write": write}


def test_leak_detection_finds_upper_email_and_rounded_salary() -> None:
    denied = SensitiveValues(
        casefolded=frozenset({"customer001@example.test", "staff member 01"}),
        exact=frozenset({"85000.60", "85000", "85001"}),
        phone_digits=frozenset({"905551234"}),
    )

    assert leaked([["CUSTOMER001@EXAMPLE.TEST"]], denied)
    assert leaked([["85001"]], denied)
    assert leaked([["Phone: +90 (555) 1234"]], denied)


def test_metric_computation_counts_layers_categories_and_false_blocks() -> None:
    attacks = [
        {
            "category": "write",
            "configurations": {
                "validator_only": _configuration("blocked_validator"),
                "db_only": _configuration("blocked_permission"),
                "full": _configuration("blocked_validator"),
            },
        },
        {
            "category": "encoding",
            "configurations": {
                "validator_only": _configuration("passed"),
                "db_only": _configuration("passed", leak=True),
                "full": _configuration("passed"),
            },
        },
    ]
    normal = [{"outcome": "ok"}, {"outcome": "false_block"}]

    metrics = compute_metrics(attacks, normal)

    assert metrics["layers"]["validator_only"] == {
        "total": 2,
        "outcomes": {
            "blocked_validator": 1,
            "blocked_permission": 0,
            "blocked_readonly": 0,
            "timeout": 0,
            "error": 0,
            "passed": 1,
        },
        "rejected": 1,
        "approved_passes": 0,
        "harmful_passes": 0,
    }
    assert metrics["layers"]["db_only"]["harmful_passes"] == 1
    assert metrics["full_by_category"]["write"]["rejected"] == 1
    assert metrics["normal"]["false_block_rate"] == 50.0


def test_check_gate_rejects_harm_unapproved_passes_and_bad_normal_queries() -> None:
    report = {
        "write_check": {"changed": False},
        "attacks": [
            {
                "id": "harm",
                "allowed_to_pass": "not enough to excuse harm",
                "configurations": {
                    "full": _configuration("passed", leak=True),
                },
            },
            {
                "id": "unapproved",
                "allowed_to_pass": None,
                "configurations": {"full": _configuration("passed")},
            },
        ],
        "normal_questions": [{"id": "q1", "outcome": "mismatch"}],
    }

    failures = check_failures(report)

    assert failures == [
        "harmful full-stack pass: harm",
        "unapproved full-stack pass: unapproved",
        "normal question q1 was mismatch",
    ]
