from text_to_sql_guardrails.guard.policy import Policy, load_policy
from text_to_sql_guardrails.guard.roles import grant_statements


def test_grant_statements_are_column_level_and_safely_quoted():
    policy = Policy(
        tables={"odd-table": frozenset({"safe", 'quote"column'})},
        default_limit=10,
        max_limit=20,
    )

    statements = grant_statements(policy, 'report"reader')

    assert statements == [
        'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "report""reader"',
        'GRANT USAGE ON SCHEMA public TO "report""reader"',
        (
            'GRANT SELECT ("quote""column", "safe") ON TABLE "public"."odd-table" '
            'TO "report""reader"'
        ),
        'ALTER ROLE "report""reader" SET default_transaction_read_only = on',
        'ALTER ROLE "report""reader" SET statement_timeout = \'3000ms\'',
    ]


def test_demo_policy_never_grants_sensitive_table_or_columns():
    sql = "\n".join(grant_statements(load_policy("config/policy.toml"), "reader"))

    assert '"staff_salaries"' not in sql
    assert '"email"' not in sql
    assert '"phone"' not in sql
