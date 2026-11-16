"""Run the offline, model-free guardrail benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

from text_to_sql_guardrails.bench.data import (
    Attack,
    Question,
    load_attacks,
    load_questions,
)
from text_to_sql_guardrails.db import create_readonly_engine
from text_to_sql_guardrails.guard.executor import (
    QueryFailed,
    QueryPermissionDenied,
    QueryResult,
    QueryTimeout,
    run_readonly,
)
from text_to_sql_guardrails.guard.policy import Policy, load_policy
from text_to_sql_guardrails.guard.roles import apply_role
from text_to_sql_guardrails.guard.validator import validate
from text_to_sql_guardrails.seed import seed_database

ROOT = Path(__file__).resolve().parents[3]
CONFIGURATIONS = ("validator_only", "db_only", "full")
OUTCOMES = (
    "blocked_validator",
    "blocked_permission",
    "blocked_readonly",
    "timeout",
    "error",
    "passed",
)
REJECTED_OUTCOMES = frozenset(
    {"blocked_validator", "blocked_permission", "blocked_readonly"}
)
README_START = "<!-- bench:guardrails:start -->"
README_END = "<!-- bench:guardrails:end -->"


@dataclass(frozen=True)
class SensitiveValues:
    casefolded: frozenset[str]
    exact: frozenset[str]
    phone_digits: frozenset[str]


def prepare_database(database_url: str, *, root: Path = ROOT) -> tuple[Engine, Engine]:
    """Rebuild the disposable shop schema and return admin/read-only engines."""

    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    alembic_config = Config(str(root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(root / "migrations"))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")
    seed_database(admin_engine)

    policy = load_policy(root / "config/policy.toml")
    role = "t2s_benchmark_readonly"
    password = "t2s-benchmark-readonly-password"
    apply_role(admin_engine, policy, role, password, statement_timeout_ms=1_000)
    readonly_url = make_url(database_url).set(username=role, password=password)
    return admin_engine, create_readonly_engine(readonly_url)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def database_checksum(engine: Engine) -> dict[str, dict[str, Any]]:
    """Hash every public table in a stable all-column order."""

    checksum: dict[str, dict[str, Any]] = {}
    inspector = inspect(engine)
    preparer = engine.dialect.identifier_preparer
    with engine.connect() as connection:
        for table in sorted(inspector.get_table_names(schema="public")):
            quoted_table = preparer.quote(table)
            columns = [
                preparer.quote(column["name"])
                for column in inspector.get_columns(table, schema="public")
            ]
            order_by = f" ORDER BY {', '.join(columns)}" if columns else ""
            rows = connection.exec_driver_sql(
                f"SELECT * FROM {quoted_table}{order_by}"
            ).fetchall()
            encoded = json.dumps(
                [[_json_value(value) for value in row] for row in rows],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            checksum[table] = {
                "rows": len(rows),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        for sequence in sorted(inspector.get_sequence_names(schema="public")):
            quoted_sequence = preparer.quote(sequence)
            last_value, is_called = connection.exec_driver_sql(
                f"SELECT last_value, is_called FROM public.{quoted_sequence}"
            ).one()
            checksum[f"sequence:{sequence}"] = {
                "last_value": _json_value(last_value),
                "is_called": bool(is_called),
            }
    return checksum


def sensitive_values(engine: Engine) -> SensitiveValues:
    """Fetch real denied values so leak detection tests data, not column labels."""

    casefolded: set[str] = set()
    exact: set[str] = set()
    phone_digits: set[str] = set()
    with engine.connect() as connection:
        for email, phone in connection.exec_driver_sql(
            "SELECT email, phone FROM customers"
        ):
            casefolded.add(str(email).casefold())
            phone_text = str(phone)
            exact.add(phone_text)
            phone_digits.add("".join(character for character in phone_text if character.isdigit()))
        for staff_name, salary in connection.exec_driver_sql(
            "SELECT staff_name, salary FROM staff_salaries"
        ):
            casefolded.add(str(staff_name).casefold())
            salary_value = Decimal(salary)
            exact.update(
                {
                    str(salary_value),
                    str(int(salary_value)),
                    str(round(salary_value)),
                }
            )
    return SensitiveValues(
        casefolded=frozenset(casefolded),
        exact=frozenset(exact),
        phone_digits=frozenset(phone_digits),
    )


def leaked(rows: list[list[Any]], denied_values: SensitiveValues) -> bool:
    for row in rows:
        for cell in row:
            cell_text = str(cell)
            if any(value in cell_text.casefold() for value in denied_values.casefolded):
                return True
            if any(value in cell_text for value in denied_values.exact):
                return True
            digits = "".join(character for character in cell_text if character.isdigit())
            if any(value in digits for value in denied_values.phone_digits):
                return True
    return False


def _run(sql: str, engine: Engine, timeout_ms: int, max_rows: int) -> tuple[str, QueryResult | None]:
    try:
        return "passed", run_readonly(sql, engine, timeout_ms=timeout_ms, max_rows=max_rows)
    except QueryTimeout:
        return "timeout", None
    except QueryPermissionDenied as error:
        outcome = (
            "blocked_readonly" if error.sqlstate == "25006" else "blocked_permission"
        )
        return outcome, None
    except QueryFailed:
        return "error", None


def _attack_result(
    attack: Attack,
    policy: Policy,
    admin_engine: Engine,
    readonly_engine: Engine,
    denied_values: SensitiveValues,
    timeout_ms: int,
    max_rows: int,
) -> dict[str, Any]:
    validation = validate(attack.sql, policy)
    violations = [violation.code.value for violation in validation.violations]

    validator_only: dict[str, Any]
    if not validation.ok:
        validator_only = {
            "outcome": "blocked_validator",
            "violations": violations,
            "leak": False,
            "write": False,
        }
    else:
        assert validation.sql is not None
        execution, result = _run(validation.sql, admin_engine, timeout_ms, max_rows)
        validator_only = {
            "outcome": "passed",
            "violations": [],
            "execution_outcome": execution,
            "leak": result is not None and leaked(result.rows, denied_values),
            "write": False,
        }

    db_outcome, db_result = _run(attack.sql, readonly_engine, timeout_ms, max_rows)
    db_only = {
        "outcome": db_outcome,
        "leak": db_result is not None and leaked(db_result.rows, denied_values),
        "write": False,
    }

    if not validation.ok:
        full = {
            "outcome": "blocked_validator",
            "violations": violations,
            "leak": False,
            "write": False,
        }
    else:
        assert validation.sql is not None
        full_outcome, full_result = _run(
            validation.sql, readonly_engine, timeout_ms, max_rows
        )
        full = {
            "outcome": full_outcome,
            "violations": [],
            "leak": full_result is not None and leaked(full_result.rows, denied_values),
            "write": False,
        }

    return {
        "id": attack.id,
        "category": attack.category,
        "note": attack.note,
        "sql": attack.sql,
        "allowed_to_pass": attack.allowed_to_pass,
        "configurations": {
            "validator_only": validator_only,
            "db_only": db_only,
            "full": full,
        },
    }


def _normal_result(
    question: Question,
    policy: Policy,
    admin_engine: Engine,
    readonly_engine: Engine,
    timeout_ms: int,
    max_rows: int,
) -> dict[str, Any]:
    validation = validate(question.gold_sql, policy)
    base = {
        "id": question.id,
        "question": question.question,
        "category": question.category,
        "difficulty": question.difficulty,
    }
    if not validation.ok:
        return {
            **base,
            "outcome": "false_block",
            "violations": [violation.code.value for violation in validation.violations],
        }
    assert validation.sql is not None
    expected_outcome, expected = _run(question.gold_sql, admin_engine, timeout_ms, max_rows)
    actual_outcome, actual = _run(validation.sql, readonly_engine, timeout_ms, max_rows)
    if expected_outcome != "passed" or actual_outcome != "passed":
        return {
            **base,
            "outcome": "error",
            "admin_outcome": expected_outcome,
            "full_outcome": actual_outcome,
        }
    assert expected is not None and actual is not None
    return {
        **base,
        "outcome": "ok" if expected.rows == actual.rows else "mismatch",
        "row_count": actual.row_count,
    }


def compute_metrics(attacks: list[dict[str, Any]], normal: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute stable summary counts from individual benchmark outcomes."""

    layers: dict[str, Any] = {}
    for configuration in CONFIGURATIONS:
        results = [row["configurations"][configuration] for row in attacks]
        outcome_counts = Counter(result["outcome"] for result in results)
        unknown = set(outcome_counts).difference(OUTCOMES)
        if unknown:
            raise ValueError(f"unknown benchmark outcomes: {', '.join(sorted(unknown))}")
        harmful = sum(
            result["outcome"] == "passed" and (result["leak"] or result["write"])
            for result in results
        )
        rejected = sum(outcome_counts[outcome] for outcome in REJECTED_OUTCOMES)
        approved_passes = sum(
            row["configurations"][configuration]["outcome"] == "passed"
            and bool(row.get("allowed_to_pass"))
            for row in attacks
        )
        layers[configuration] = {
            "total": len(results),
            "outcomes": {outcome: outcome_counts[outcome] for outcome in OUTCOMES},
            "rejected": rejected,
            "approved_passes": approved_passes,
            "harmful_passes": harmful,
        }

    categories: dict[str, Any] = {}
    for category in sorted({row["category"] for row in attacks}):
        selected = [row for row in attacks if row["category"] == category]
        outcome_counts = Counter(
            row["configurations"]["full"]["outcome"] for row in selected
        )
        harmful = sum(
            row["configurations"]["full"]["outcome"] == "passed"
            and (
                row["configurations"]["full"]["leak"]
                or row["configurations"]["full"]["write"]
            )
            for row in selected
        )
        categories[category] = {
            "total": len(selected),
            "outcomes": {outcome: outcome_counts[outcome] for outcome in OUTCOMES},
            "rejected": sum(
                outcome_counts[outcome] for outcome in REJECTED_OUTCOMES
            ),
            "approved_passes": sum(
                row["configurations"]["full"]["outcome"] == "passed"
                and bool(row.get("allowed_to_pass"))
                for row in selected
            ),
            "harmful_passes": harmful,
        }

    normal_counts = Counter(row["outcome"] for row in normal)
    normal_total = len(normal)
    false_blocks = normal_counts["false_block"]
    return {
        "layers": layers,
        "full_by_category": categories,
        "normal": {
            "total": normal_total,
            "ok": normal_counts["ok"],
            "false_block": false_blocks,
            "mismatch": normal_counts["mismatch"],
            "error": normal_counts["error"],
            "false_block_rate": round(
                (false_blocks / normal_total * 100) if normal_total else 0.0, 2
            ),
        },
    }


def run_benchmark(
    admin_engine: Engine,
    readonly_engine: Engine,
    policy: Policy,
    attacks: list[Attack],
    questions: list[Question],
    *,
    timeout_ms: int = 1_000,
    max_rows: int = 500,
) -> dict[str, Any]:
    denied_values = sensitive_values(admin_engine)
    before = database_checksum(admin_engine)
    attack_results = [
        _attack_result(
            attack,
            policy,
            admin_engine,
            readonly_engine,
            denied_values,
            timeout_ms,
            max_rows,
        )
        for attack in attacks
    ]
    after = database_checksum(admin_engine)
    write_changed = before != after
    if write_changed:
        for attack in attack_results:
            for configuration in CONFIGURATIONS:
                if attack["configurations"][configuration]["outcome"] == "passed":
                    attack["configurations"][configuration]["write"] = True

    normal_results = [
        _normal_result(
            question,
            policy,
            admin_engine,
            readonly_engine,
            timeout_ms,
            max_rows,
        )
        for question in questions
    ]
    metrics = compute_metrics(attack_results, normal_results)
    with admin_engine.connect() as connection:
        postgres_version = str(connection.scalar(text("SHOW server_version")))
    return {
        "mode": "guardrails",
        "generated_at": datetime.now(UTC).isoformat(),
        "versions": {
            "python": platform.python_version(),
            "postgresql": postgres_version,
            "sqlglot": version("sqlglot"),
            "pyyaml": version("pyyaml"),
        },
        "parameters": {"timeout_ms": timeout_ms, "max_rows": max_rows},
        "write_check": {"changed": write_changed, "before": before, "after": after},
        "metrics": metrics,
        "attacks": attack_results,
        "normal_questions": normal_results,
    }


def check_failures(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if report["write_check"]["changed"]:
        failures.append("database checksum changed during attack run")
    for attack in report["attacks"]:
        full = attack["configurations"]["full"]
        if full["outcome"] == "passed" and (full["leak"] or full["write"]):
            failures.append(f"harmful full-stack pass: {attack['id']}")
        if full["outcome"] == "passed" and not attack["allowed_to_pass"]:
            failures.append(f"unapproved full-stack pass: {attack['id']}")
    for question in report["normal_questions"]:
        if question["outcome"] != "ok":
            failures.append(
                f"normal question {question['id']} was {question['outcome']}"
            )
    return failures


def summary_tables(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    full = metrics["layers"]["full"]
    lines = [
        (
            f"Full stack: **rejected {full['rejected']}**, "
            f"**neutralized {full['approved_passes']}** "
            "(`allowed_to_pass`, rewritten to safe SQL), "
            f"**harmful {full['harmful_passes']}**."
        ),
        "",
        "| Configuration | Validator | Permission | Read-only | Timeout | Error | Passed | Harmful |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    labels = {
        "validator_only": "Validator only",
        "db_only": "Database only",
        "full": "Full stack",
    }
    for key in CONFIGURATIONS:
        row = metrics["layers"][key]
        outcomes = row["outcomes"]
        lines.append(
            f"| {labels[key]} | {outcomes['blocked_validator']} | "
            f"{outcomes['blocked_permission']} | {outcomes['blocked_readonly']} | "
            f"{outcomes['timeout']} | {outcomes['error']} | {outcomes['passed']} | "
            f"{row['harmful_passes']} |"
        )
    lines.extend(
        [
            "",
            (
                "| Full-stack category | Validator | Permission | Read-only | "
                "Timeout | Error | Neutralized | Harmful |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for category, row in metrics["full_by_category"].items():
        outcomes = row["outcomes"]
        lines.append(
            f"| `{category}` | {outcomes['blocked_validator']} | "
            f"{outcomes['blocked_permission']} | {outcomes['blocked_readonly']} | "
            f"{outcomes['timeout']} | {outcomes['error']} | "
            f"{row['approved_passes']} | {row['harmful_passes']} |"
        )
    normal = metrics["normal"]
    lines.extend(
        [
            "",
            "| Normal queries | OK | False blocks | Mismatches | Errors | False-block rate |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
            (
                f"| {normal['total']} | {normal['ok']} | {normal['false_block']} | "
                f"{normal['mismatch']} | {normal['error']} | "
                f"{normal['false_block_rate']:.2f}% |"
            ),
        ]
    )
    return "\n".join(lines)


def markdown_report(report: dict[str, Any]) -> str:
    db_passes = [
        attack for attack in report["attacks"]
        if attack["configurations"]["db_only"]["outcome"] == "passed"
    ]
    validator_passes = [
        attack for attack in report["attacks"]
        if attack["configurations"]["validator_only"]["outcome"] == "passed"
    ]

    def pass_lines(rows: list[dict[str, Any]]) -> list[str]:
        if not rows:
            return ["- None."]
        return [
            f"- `{row['id']}` (`{row['category']}`): {row['note']}"
            for row in rows
        ]

    return "\n".join(
        [
            "# Guardrail benchmark",
            "",
            f"Generated: `{report['generated_at']}`",
            "",
            summary_tables(report),
            "",
            "## Attacks passed by the database layer alone",
            "",
            *pass_lines(db_passes),
            "",
            "## Attacks passed by the validator alone",
            "",
            *pass_lines(validator_passes),
            "",
            "## Write check",
            "",
            (
                "Database contents changed: "
                f"`{str(report['write_check']['changed']).lower()}`."
            ),
            "",
        ]
    )


def write_results(report: dict[str, Any], out_dir: str | Path) -> tuple[Path, Path]:
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "guardrails.json"
    markdown_path = destination / "guardrails.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def update_readme(report: dict[str, Any], path: str | Path) -> None:
    readme = Path(path)
    content = readme.read_text(encoding="utf-8")
    if content.count(README_START) != 1 or content.count(README_END) != 1:
        raise ValueError("README benchmark markers must each appear exactly once")
    before, remainder = content.split(README_START, maxsplit=1)
    _, after = remainder.split(README_END, maxsplit=1)
    generated = f"{README_START}\n{summary_tables(report)}\n{README_END}"
    readme.write_text(before + generated + after, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("guardrails", "llm"), default="guardrails")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--update-readme", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--effort", choices=("low", "medium", "high"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only", choices=("questions", "attacks"))
    parser.add_argument("--yes-spend", action="store_true")
    parser.add_argument("--fake", action="store_true")
    return parser


def _guardrails_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if any(
        value
        for value in (
            args.model,
            args.effort,
            args.limit,
            args.only,
            args.yes_spend,
            args.fake,
        )
    ):
        parser.error("LLM options require --mode llm")

    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        parser.error("TEST_DATABASE_URL is required for the guardrails benchmark")
    selected_out = args.out or Path("bench/results")
    out_dir = selected_out if selected_out.is_absolute() else ROOT / selected_out
    attacks = load_attacks(ROOT / "bench/attacks.yaml")
    questions = load_questions(ROOT / "bench/questions.yaml")
    policy = load_policy(ROOT / "config/policy.toml")
    admin_engine, readonly_engine = prepare_database(database_url)
    try:
        report = run_benchmark(
            admin_engine, readonly_engine, policy, attacks, questions
        )
        json_path, markdown_path = write_results(report, out_dir)
        if args.update_readme:
            update_readme(report, ROOT / "README.md")
        print(f"Wrote {json_path}")
        print(f"Wrote {markdown_path}")
        print(summary_tables(report))
        failures = check_failures(report) if args.check else []
        if failures:
            for failure in failures:
                print(f"CHECK FAILED: {failure}")
            return 1
    finally:
        readonly_engine.dispose()
        admin_engine.dispose()
    return 0


def _llm_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from text_to_sql_guardrails.bench import llm as llm_bench
    from text_to_sql_guardrails.bench.data import load_attack_prompts
    from text_to_sql_guardrails.config import Settings
    from text_to_sql_guardrails.llm.anthropic_gen import AnthropicGenerator
    from text_to_sql_guardrails.llm.base import LlmNotConfigured
    from text_to_sql_guardrails.llm.prompt import build_schema_prompt

    if args.check:
        parser.error("--check is guardrails-only; LLM mode has no CI gate")
    if not args.model or not args.effort:
        parser.error("--mode llm requires --model and --effort")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.fake and args.yes_spend:
        parser.error("--fake and --yes-spend cannot be used together")
    if args.fake and args.update_readme:
        parser.error("fake benchmark results cannot update README")

    questions = load_questions(ROOT / "bench/questions.yaml")
    attacks = load_attack_prompts(ROOT / "bench/attack_prompts.yaml")
    if args.only == "questions":
        attacks = []
    elif args.only == "attacks":
        questions = []
    if args.limit is not None:
        questions = questions[: args.limit]
        attacks = attacks[: args.limit]

    policy = load_policy(ROOT / "config/policy.toml")
    prices = llm_bench.load_prices(ROOT / "config/prices.toml")
    if not args.yes_spend and not args.fake:
        prompts = [question.question for question in questions] + [
            attack.question for attack in attacks
        ]
        estimate = llm_bench.estimate_run_cost(
            args.model, build_schema_prompt(policy), prompts, prices
        )
        print("Cost estimate only; no model API call was made.")
        print(
            "Assumptions: two calls per prompt (worst-case retry), "
            "system + schema + question characters / 4 input tokens (retry adds the "
            "previous attempt), 400 output tokens per call."
        )
        print(
            f"Prompts: {len(prompts)}; calls: {estimate['calls']}; "
            f"input tokens: {estimate['input_tokens']}; "
            f"output tokens: {estimate['output_tokens']}"
        )
        if estimate["cost_usd"] is None:
            print(f"Estimated cost: unknown (no price for {args.model})")
        else:
            print(f"Estimated cost: ${estimate['cost_usd']:.6f} USD")
        print("Re-run with --yes-spend to call the model.")
        return 0

    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        parser.error("TEST_DATABASE_URL is required to execute the LLM benchmark")
    if args.fake:
        generator = llm_bench.GoldSqlGenerator(questions, args.model)
    else:
        settings = Settings(
            _env_file=None,
            llm_model=args.model,
            llm_effort=args.effort,
        )
        generator = AnthropicGenerator(settings)

    admin_engine, readonly_engine = prepare_database(database_url)
    try:
        try:
            report = llm_bench.run_benchmark(
                admin_engine,
                readonly_engine,
                policy,
                questions,
                attacks,
                generator,
                prices,
                model=args.model,
                effort=args.effort,
                fake=args.fake,
            )
        except LlmNotConfigured:
            print(
                "Anthropic credentials are not configured. Use a Console API key or "
                "run `ant auth login`; a Claude Code login does not count.",
                file=sys.stderr,
            )
            return 2
        if args.out is not None:
            out_dir = args.out if args.out.is_absolute() else ROOT / args.out
        elif args.fake:
            out_dir = Path(tempfile.mkdtemp(prefix="t2s-bench-fake-"))
        else:
            out_dir = ROOT / "bench/results"
        json_path, markdown_path = llm_bench.write_results(report, out_dir)
        print(f"Wrote {json_path}")
        print(f"Wrote {markdown_path}")
        print(llm_bench.summary(report))
        if args.update_readme:
            llm_bench.update_readme(report, ROOT / "README.md")
    finally:
        readonly_engine.dispose()
        admin_engine.dispose()
    return 0


def cli(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.mode == "llm":
        return _llm_cli(args, parser)
    return _guardrails_cli(args, parser)


def main() -> None:
    raise SystemExit(cli())


if __name__ == "__main__":
    main()
