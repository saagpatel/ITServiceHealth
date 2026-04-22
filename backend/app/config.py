"""Application settings loaded from environment variables and .env file."""

from pathlib import Path

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_path: str = "data.db"
    poll_interval_seconds: int = Field(default=60, gt=0, le=3600)
    slack_webhook_url: HttpUrl | None = None
    host: str = "127.0.0.1"
    port: int = Field(default=8000, gt=0, le=65535)
    log_level: str = "INFO"
    seed_demo_data: bool = False

    # Admin write endpoints require this token in the Authorization header.
    # If unset, admin endpoints refuse all requests (fail closed).
    admin_api_token: str | None = None

    # Comma-separated list of CORS origins. Default covers local dev only.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return upper

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def slack_webhook_url_str(self) -> str | None:
        """HttpUrl as a plain string for httpx.post()."""
        return str(self.slack_webhook_url) if self.slack_webhook_url else None

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
