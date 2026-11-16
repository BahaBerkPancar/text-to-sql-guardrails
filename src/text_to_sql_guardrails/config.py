from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


def resolve_policy_path(path: str | Path) -> Path:
    """Resolve a policy path consistently, independent of the current directory."""

    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://app:app@127.0.0.1:5432/app"
    readonly_database_url: str = (
        "postgresql+psycopg://t2s_readonly:change-me@127.0.0.1:5432/app"
    )
    readonly_role: str = "t2s_readonly"
    readonly_password: str = "change-me"
    statement_timeout_ms: int = Field(default=3_000, gt=0)
    policy_path: str = "config/policy.toml"
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"
    llm_timeout_s: float = Field(default=60, gt=0)


settings = Settings()
