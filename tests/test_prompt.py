from text_to_sql_guardrails.guard.policy import load_policy
from text_to_sql_guardrails.llm.prompt import SYSTEM_PROMPT, build_schema_prompt


def test_schema_prompt_is_stable_and_contains_only_allowed_schema():
    policy = load_policy("config/policy.toml")

    first = build_schema_prompt(policy)
    second = build_schema_prompt(policy)

    assert first == second
    assert "customers" in first
    assert "ordered_at: TIMESTAMP WITHOUT TIME ZONE" in first
    assert "email" not in first
    assert "phone" not in first
    assert "staff_salaries" not in first


def test_system_prompt_treats_the_question_as_untrusted():
    lowered = SYSTEM_PROMPT.lower()

    assert "postgresql" in lowered
    assert "one select" in lowered
    assert "untrusted" in lowered
    assert "cannot_answer" in lowered
