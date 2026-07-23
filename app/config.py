"""Application configuration.

Settings are read from environment variables, so the same code runs against
SQLite locally and PostgreSQL in production without any change.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # SQLite by default so the app runs with no setup. Point this at Postgres
    # for production, e.g. postgresql+psycopg2://user:pass@host:5432/db
    database_url: str = "sqlite:///./inventory.db"

    # Echo SQL to stdout (handy while debugging transactions).
    sql_echo: bool = False

    # How many times to retry a movement when an optimistic-lock (version)
    # conflict is detected before giving up with a 409.
    max_write_retries: int = 5

    @field_validator("database_url")
    @classmethod
    def _normalise_driver(cls, value: str) -> str:
        """Force the psycopg (v3) driver onto bare Postgres URLs.

        Hosting dashboards hand out plain ``postgresql://`` strings, and
        SQLAlchemy maps that to psycopg2 -- a package this project does not
        install. Rewriting it here means pasting a provider URL verbatim just
        works, instead of failing at import time with ModuleNotFoundError.
        """
        if value.startswith("postgres://"):  # some providers still emit this
            value = value.replace("postgres://", "postgresql://", 1)
        if value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value


settings = Settings()
