import pytest
from pydantic import ValidationError

from text_to_sql_guardrails.config import ROOT, Settings, resolve_policy_path


def test_policy_path_is_resolved_from_repository_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert resolve_policy_path("config/policy.toml") == ROOT / "config/policy.toml"
    assert resolve_policy_path(tmp_path / "policy.toml") == tmp_path / "policy.toml"


def test_statement_timeout_must_be_positive():
    with pytest.raises(ValidationError):
        Settings(statement_timeout_ms=0)
