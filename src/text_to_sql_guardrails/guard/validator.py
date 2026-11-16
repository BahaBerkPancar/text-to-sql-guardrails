"""Validate and safely rewrite LLM-produced PostgreSQL SELECT statements."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlglot import exp, parse
from sqlglot.errors import OptimizeError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from text_to_sql_guardrails.guard.policy import Policy


class ViolationCode(StrEnum):
    PARSE_ERROR = "PARSE_ERROR"
    MULTI_STATEMENT = "MULTI_STATEMENT"
    NOT_SELECT = "NOT_SELECT"
    FORBIDDEN_NODE = "FORBIDDEN_NODE"
    TABLE_NOT_ALLOWED = "TABLE_NOT_ALLOWED"
    COLUMN_NOT_ALLOWED = "COLUMN_NOT_ALLOWED"
    FUNCTION_NOT_ALLOWED = "FUNCTION_NOT_ALLOWED"
    BAD_LIMIT = "BAD_LIMIT"
    EMPTY = "EMPTY"


@dataclass(frozen=True)
class Violation:
    code: ViolationCode
    message: str


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    sql: str | None
    violations: list[Violation]


_FORBIDDEN_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
    exp.Copy,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Grant,
    exp.Into,
    exp.Lock,
    exp.TableSample,
)

# This is intentionally narrow. New sqlglot function classes are denied until reviewed.
_SAFE_FUNCTION_TYPES = (
    exp.Abs,
    exp.ArrayAgg,
    exp.Avg,
    exp.Cast,
    exp.Case,
    exp.Ceil,
    exp.Coalesce,
    exp.Concat,
    exp.ConcatWs,
    exp.Count,
    exp.CurrentDate,
    exp.CurrentTime,
    exp.CurrentTimestamp,
    exp.DateAdd,
    exp.DateDiff,
    exp.DateSub,
    exp.DateTrunc,
    exp.DenseRank,
    exp.Extract,
    exp.Exists,
    exp.Floor,
    exp.Greatest,
    exp.GroupConcat,
    exp.Initcap,
    exp.If,
    exp.Lag,
    exp.Lead,
    exp.Least,
    exp.Length,
    exp.Lower,
    exp.Max,
    exp.Min,
    exp.Mod,
    exp.Nullif,
    exp.PercentileCont,
    exp.PercentileDisc,
    exp.Pow,
    exp.Rank,
    exp.Replace,
    exp.Round,
    exp.RowNumber,
    exp.Sqrt,
    exp.Stddev,
    exp.StddevPop,
    exp.StddevSamp,
    exp.Substring,
    exp.Sum,
    exp.TimestampTrunc,
    exp.Trim,
    exp.TryCast,
    exp.Upper,
    exp.Variance,
    exp.VariancePop,
)


def _is_select_tree(expression: exp.Expression) -> bool:
    if isinstance(expression, exp.Subquery):
        return _is_select_tree(expression.this)
    if isinstance(expression, exp.Select):
        return True
    if isinstance(expression, exp.SetOperation):
        return _is_select_tree(expression.this) and _is_select_tree(expression.expression)
    return False


def _function_name(function: exp.Func) -> str:
    if isinstance(function, exp.Anonymous):
        return function.name.casefold()
    return function.sql_name().casefold()


def _literal_nonnegative_int(expression: exp.Expression | None) -> int | None:
    if not isinstance(expression, exp.Literal) or not expression.is_int:
        return None
    try:
        value = int(expression.this)
    except (TypeError, ValueError):
        return None
    return value


def _limit_value(limit: exp.Expression) -> exp.Expression | None:
    if isinstance(limit, exp.Fetch):
        return limit.args.get("count")
    return limit.args.get("expression")


def _set_limit_value(limit: exp.Expression, value: int) -> None:
    key = "count" if isinstance(limit, exp.Fetch) else "expression"
    limit.set(key, exp.Literal.number(value))


def _normalize_policy_identifiers(expression: exp.Expression, policy: Policy) -> None:
    """Canonicalize case-insensitive policy names before schema qualification."""

    allowed_columns = set().union(*policy.tables.values())
    for table in expression.find_all(exp.Table):
        table_name = table.name.casefold()
        schema_name = table.db.casefold()
        if not table.catalog and schema_name in {"", "public"} and table_name in policy.tables:
            table.set("this", exp.to_identifier(table_name))
            if schema_name:
                table.set("db", exp.to_identifier(schema_name))

    for column in expression.find_all(exp.Column):
        column_name = column.name.casefold()
        if column_name in allowed_columns:
            column.set("this", exp.to_identifier(column_name))


def validate(sql: str, policy: Policy) -> ValidationResult:
    """Return a qualified, row-limited query or machine-readable violations."""

    if not sql.strip():
        return ValidationResult(False, None, [Violation(ViolationCode.EMPTY, "SQL is empty")])

    try:
        statements = [statement for statement in parse(sql, read="postgres") if statement is not None]
    except Exception as error:  # noqa: BLE001 - malformed generated SQL must never escape
        return ValidationResult(
            False,
            None,
            [Violation(ViolationCode.PARSE_ERROR, f"SQL could not be parsed: {error}")],
        )

    if not statements:
        return ValidationResult(False, None, [Violation(ViolationCode.EMPTY, "SQL is empty")])
    if len(statements) != 1:
        return ValidationResult(
            False,
            None,
            [Violation(ViolationCode.MULTI_STATEMENT, "exactly one SQL statement is required")],
        )

    expression = statements[0]
    while isinstance(expression, exp.Subquery) and _is_select_tree(expression.this):
        expression = expression.this
    violations: list[Violation] = []
    seen: set[tuple[ViolationCode, str]] = set()

    def add(code: ViolationCode, message: str) -> None:
        key = (code, message)
        if key not in seen:
            seen.add(key)
            violations.append(Violation(code, message))

    if not _is_select_tree(expression):
        add(ViolationCode.NOT_SELECT, "the statement root must be SELECT or a SELECT set operation")

    for node in expression.walk():
        if isinstance(node, _FORBIDDEN_TYPES):
            add(ViolationCode.FORBIDDEN_NODE, f"forbidden SQL node: {type(node).__name__}")

    scopes = list(traverse_scope(expression))
    cte_references: set[int] = set()
    for scope in scopes:
        real_aliases: set[str] = set()
        for table in scope.tables:
            if not isinstance(scope.sources.get(table.alias_or_name), exp.Table):
                cte_references.add(id(table))
        for alias, source in scope.sources.items():
            if not isinstance(source, exp.Table):
                continue
            real_aliases.add(alias.casefold())
            table_name = source.name.casefold()
            schema_name = source.db.casefold()
            catalog_name = source.catalog.casefold()
            if catalog_name or schema_name not in {"", "public"} or table_name not in policy.tables:
                add(
                    ViolationCode.TABLE_NOT_ALLOWED,
                    f"table is not allowed: {source.sql(dialect='postgres')}",
                )

        for column in scope.columns:
            if not column.table and column.name.casefold() in real_aliases:
                add(
                    ViolationCode.COLUMN_NOT_ALLOWED,
                    f"whole-row reference is not allowed: {column.name}",
                )

    for table in expression.find_all(exp.Table):
        if id(table) in cte_references:
            continue
        table_name = table.name.casefold()
        schema_name = table.db.casefold()
        catalog_name = table.catalog.casefold()
        if catalog_name or schema_name not in {"", "public"} or table_name not in policy.tables:
            add(
                ViolationCode.TABLE_NOT_ALLOWED,
                f"table is not allowed: {table.sql(dialect='postgres')}",
            )

    for function in expression.find_all(exp.Func):
        function_name = _function_name(function)
        if type(function) not in _SAFE_FUNCTION_TYPES and function_name not in policy.extra_functions:
            add(
                ViolationCode.FUNCTION_NOT_ALLOWED,
                f"function is not allowed: {function_name}",
            )

    rewritten = expression.copy()
    _normalize_policy_identifiers(rewritten, policy)
    for limit in rewritten.find_all((exp.Limit, exp.Fetch)):
        value = _literal_nonnegative_int(_limit_value(limit))
        if value is None:
            add(ViolationCode.BAD_LIMIT, "LIMIT/FETCH must be a non-negative integer literal")
        elif value > policy.max_limit:
            _set_limit_value(limit, policy.max_limit)

    for offset in rewritten.find_all(exp.Offset):
        if _literal_nonnegative_int(offset.args.get("expression")) is None:
            add(ViolationCode.BAD_LIMIT, "OFFSET must be a non-negative integer literal")

    if rewritten.args.get("limit") is None:
        rewritten.set("limit", exp.Limit(expression=exp.Literal.number(policy.default_limit)))

    if _is_select_tree(rewritten):
        schema = {
            table: {column: "UNKNOWN" for column in sorted(columns)}
            for table, columns in policy.tables.items()
        }
        try:
            rewritten = qualify(
                rewritten,
                dialect="postgres",
                schema=schema,
                quote_identifiers=False,
                validate_qualify_columns=True,
            )
        except OptimizeError as error:
            add(ViolationCode.COLUMN_NOT_ALLOWED, f"column is not allowed or is ambiguous: {error}")
        except Exception as error:  # noqa: BLE001 - qualification must fail closed
            add(ViolationCode.PARSE_ERROR, f"SQL could not be safely qualified: {error}")

        relation_names: set[str] = set()
        for table in rewritten.find_all(exp.Table):
            relation_names.add(table.name.casefold())
            relation_names.add(table.alias_or_name.casefold())
        for column in rewritten.find_all(exp.Column):
            if not column.table and column.name.casefold() in relation_names:
                add(
                    ViolationCode.COLUMN_NOT_ALLOWED,
                    f"whole-row reference is not allowed: {column.name}",
                )

        for star in rewritten.find_all(exp.Star):
            if not star.find_ancestor(exp.Count, exp.Exists):
                add(ViolationCode.COLUMN_NOT_ALLOWED, "wildcard column could not be safely expanded")

    if violations:
        return ValidationResult(False, None, violations)
    return ValidationResult(True, rewritten.sql(dialect="postgres", comments=False), [])
