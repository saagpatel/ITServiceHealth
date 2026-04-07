"""Application settings loaded from environment variables and .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_path: str = "data.db"
    poll_interval_seconds: int = 60
    slack_webhook_url: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    seed_demo_data: bool = False

    @property
    def services_yaml_path(self) -> Path:
        return Path(__file__).parent.parent / "config" / "services.yaml"

    @property
    def dependencies_yaml_path(self) -> Path:
        return Path(__file__).parent.parent / "config" / "dependencies.yaml"

    @property
    def migrations_dir(self) -> Path:
        return Path(__file__).parent.parent / "migrations"


settings = Settings()
