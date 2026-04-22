"""Sentry integration with secret-scrubbing.

No-op when SENTRY_DSN is unset — safe to call unconditionally at startup.
The `before_send` hook strips well-known secrets from event payloads so
a stray log line with a Slack webhook URL doesn't leak to Sentry's UI.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_SECRET_PATTERNS = [
    re.compile(r"hooks\.slack\.com/services/[A-Za-z0-9/_-]+"),
    re.compile(r"Bearer [A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"authorization: [^\s]+", re.IGNORECASE),
]
_REDACTION = "[REDACTED]"


def _scrub(value: Any) -> Any:
    """Recursively redact secret patterns from strings nested inside an
    arbitrary JSON-like payload."""
    if isinstance(value, str):
        scrubbed = value
        for pattern in _SECRET_PATTERNS:
            scrubbed = pattern.sub(_REDACTION, scrubbed)
        return scrubbed
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _before_send(event: dict, _hint: dict) -> dict:
    """Sentry before_send hook. Returns the (possibly scrubbed) event."""
    return _scrub(event)


def configure_sentry() -> None:
    """Initialize Sentry if SENTRY_DSN is configured. Idempotent."""
    dsn = settings.sentry_dsn_str
    if not dsn:
        logger.debug("SENTRY_DSN not set, skipping Sentry init")
        return

    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware  # noqa: F401
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        before_send=_before_send,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
        ],
    )
    logger.info("Sentry initialized (environment=%s)", settings.sentry_environment)
