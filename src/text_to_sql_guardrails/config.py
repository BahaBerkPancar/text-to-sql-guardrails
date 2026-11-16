from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://app:app@127.0.0.1:5432/app"
    readonly_database_url: str = (
        "postgresql+psycopg://t2s_readonly:change-me@127.0.0.1:5432/app"
    )
    readonly_role: str = "t2s_readonly"
    readonly_password: str = "change-me"
    statement_timeout_ms: int = 3_000
    policy_path: str = "config/policy.toml"


settings = Settings()
