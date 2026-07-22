"""Application configuration.

Everything is driven by environment variables (12-factor style) so the same
image runs against SQLite locally and Postgres in Docker/production without a
code change.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # SQLite by default => zero-setup local run. Point this at Postgres for
    # production, e.g. postgresql+psycopg2://user:pass@host:5432/db
    database_url: str = "sqlite:///./inventory.db"

    # Echo SQL to stdout (handy while debugging transactions).
    sql_echo: bool = False

    # How many times to retry a movement when an optimistic-lock (version)
    # conflict is detected before giving up with a 409.
    max_write_retries: int = 5


settings = Settings()
