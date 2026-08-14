"""Runtime configuration, all overridable by environment variable."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVELLIA_", env_file=".env")

    # The JSONL file we ingest at startup. One FHIR resource per line.
    data_file: str = "instructions/backend-takehome-fhir-resources.txt"

    # SQLite by default so the whole app is one `docker run` with no services
    # to stand up. SQLAlchemy keeps the door open to Postgres later.
    db_url: str = "sqlite:///./novellia.db"

    # Rebuild the database from data_file on every startup. True is the right
    # default for a take-home: the file is the source of truth and there are no
    # migrations to reason about.
    reset_on_startup: bool = True

    # Default and maximum page sizes for list endpoints.
    default_page_size: int = 50
    max_page_size: int = 500

    # Suppresses the startup schema/ingest hook. Tests build their own isolated
    # database and choose their own fixture data, so the app must not also load
    # the real file underneath them.
    testing: bool = False


settings = Settings()
