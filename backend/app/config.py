"""Application settings loaded from environment variables and .env file."""

from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr, field_validator
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
    # Optional path for Python-side file logging. When unset (default),
    # logs go to stderr so launchd's StandardOutPath redirection handles
    # rotation. Set this if you want Python to write the file directly —
    # in that case logging_config uses WatchedFileHandler to survive
    # newsyslog rotation (rename + create of a new inode).
    log_file: str | None = None
    seed_demo_data: bool = False
    postmortems_enabled: bool = False
    postmortems_dir: str = "docs/postmortems"
    backup_dir: str = "backups"
    backup_time_hour: int = 2  # UTC hour for daily backup
    backup_retention_days: int = 7

    # SLO burn-rate alerting (Phase 7 item 2)
    slo_burn_rate_enabled: bool = False
    slo_target_percent: float = Field(default=99.9, ge=90.0, le=99.99)
    slo_burn_rate_check_interval_seconds: int = Field(default=300, gt=0, le=3600)
    slo_burn_rate_fast_threshold: float = Field(default=14.4, gt=0, le=100.0)
    slo_burn_rate_slow_threshold: float = Field(default=6.0, gt=0, le=100.0)
    slo_burn_rate_ticket_threshold: float = Field(default=1.0, gt=0, le=100.0)

    # Phase 7 — Inbound Statuspage webhooks
    # Feature-gated off by default; set WEBHOOKS_ENABLED=true + a shared secret
    # that matches what you configured in Statuspage subscriber settings.
    webhooks_enabled: bool = False
    statuspage_webhook_secret: SecretStr | None = None

    # Phase 2B — Slack ack flow
    # Feature-gated off by default; set SLACK_ACK_ENABLED=true + the signing
    # secret from your Slack app's "Basic Information → App Credentials" page.
    slack_ack_enabled: bool = False
    # Feature-gated off by default; set SLACK_SLASH_ENABLED=true once the
    # Slack app has a slash command pointing at POST /api/slack/slash and
    # SLACK_SIGNING_SECRET is configured.
    slack_slash_enabled: bool = False
    slack_signing_secret: SecretStr | None = None

    # Admin write endpoints require this token in the Authorization header.
    # If unset, admin endpoints refuse all requests (fail closed).
    admin_api_token: str | None = None

    # Comma-separated list of CORS origins. Default covers local dev only.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Poller resilience knobs — see app/poller/resilience.py
    breaker_threshold: int = Field(default=3, gt=0, le=20)
    breaker_ttl_seconds: float = Field(default=300.0, gt=0, le=3600)
    poller_failure_threshold: int = Field(default=3, gt=0, le=20)

    # Separate webhook for poller-health alerts ("the dashboard is blind").
    # Keep this distinct from vendor-outage alerts so responders can tell the
    # difference at a glance. If unset, poller-health alerts fall back to the
    # main webhook but are tagged as such.
    poller_health_slack_webhook_url: HttpUrl | None = None

    # Alert-quality knobs (Phase 2) — see app/alerting/ and change_detector.py
    alert_confirm_threshold_polls: int = Field(default=3, gt=0, le=20)
    alert_recovery_threshold_polls: int = Field(default=2, gt=0, le=20)
    alert_min_state_duration_seconds: int = Field(default=600, ge=0, le=86400)
    alert_dedup_window_seconds: int = Field(default=86400, gt=0, le=604800)
    # If an upstream service with at least this many unhealthy dependents
    # changes state, emit one aggregated alert instead of one per dependent.
    dependency_correlation_threshold: int = Field(default=3, gt=0, le=100)

    # Observability (Phase 3)
    # Pretty console output in dev, JSON in prod. JSON is cheap to parse
    # and preserves contextvars (poll_cycle_id etc.) as first-class fields.
    log_json: bool = True

    # Sentry DSN — leave unset to disable error tracking entirely.
    sentry_dsn: HttpUrl | None = None
    sentry_environment: str = "production"
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    # Dead-man's switch — a URL to GET every 30s to prove the scheduler
    # is alive. Healthchecks.io and Cronitor both accept a bare URL ping.
    # Leave unset to disable external dead-man pings.
    healthcheck_ping_url: HttpUrl | None = None
    heartbeat_interval_seconds: int = Field(default=30, gt=0, le=600)
    # /healthz returns 503 when the heartbeat is this stale — launchd (or
    # whatever supervisor is in front) should then restart the process.
    heartbeat_stale_after_seconds: int = Field(default=120, gt=0, le=3600)

    # Data lifecycle (Phase 4)
    # Rows older than this are purged weekly. Set to 0 to disable retention.
    retention_days_status_events: int = Field(default=90, ge=0, le=3650)
    retention_days_alert_sent_log: int = Field(default=90, ge=0, le=3650)
    # How often the scheduler runs retention + checkpoint. Retention is
    # cheap enough that running weekly is fine; WAL checkpoints need to
    # happen more often to stop the -wal file from growing without bound.
    retention_interval_hours: int = Field(default=168, gt=0, le=8760)  # 1 week
    wal_checkpoint_interval_hours: int = Field(default=24, gt=0, le=168)

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
    def poller_health_slack_webhook_url_str(self) -> str | None:
        """Separate poller-health webhook URL as a plain string."""
        return (
            str(self.poller_health_slack_webhook_url)
            if self.poller_health_slack_webhook_url
            else None
        )

    @property
    def sentry_dsn_str(self) -> str | None:
        return str(self.sentry_dsn) if self.sentry_dsn else None

    @property
    def healthcheck_ping_url_str(self) -> str | None:
        return str(self.healthcheck_ping_url) if self.healthcheck_ping_url else None

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
