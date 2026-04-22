"""Dead-man's switch — prove the scheduler is alive.

An APScheduler job ticks every `heartbeat_interval_seconds` (default 30s)
and does two things:

1. Writes the current wall-clock timestamp to a module-level variable so
   `/healthz` can answer "is the scheduler still running?".

2. Optionally GETs a `HEALTHCHECK_PING_URL` (Healthchecks.io / Cronitor /
   similar). If the whole process, the VPN, or the Mac Mini itself dies,
   the external monitor notices in minutes and pages an operator.

The heartbeat timestamp is also mirrored into the
`scheduler_last_heartbeat_seconds` Prometheus gauge so internal scrapers
see the same signal.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import httpx

from app.config import settings
from app.observability.metrics import SCHEDULER_LAST_HEARTBEAT_SECONDS

logger = logging.getLogger(__name__)

# Seeded at module import so an early /healthz read before the first
# heartbeat tick doesn't immediately 503. The scheduler is expected to
# tick within `heartbeat_interval_seconds` of startup anyway.
_last_heartbeat_monotonic: float = time.monotonic()


def get_seconds_since_heartbeat() -> float:
    """How long ago the scheduler last proved it was alive."""
    return time.monotonic() - _last_heartbeat_monotonic


def is_heartbeat_fresh() -> bool:
    """True if the last heartbeat is within the stale threshold."""
    return get_seconds_since_heartbeat() < settings.heartbeat_stale_after_seconds


def _mark_heartbeat() -> None:
    """Record a heartbeat in both the in-process state and the metric."""
    global _last_heartbeat_monotonic
    _last_heartbeat_monotonic = time.monotonic()
    SCHEDULER_LAST_HEARTBEAT_SECONDS.set(0.0)


async def heartbeat_tick(http_client_factory: Callable[[], httpx.AsyncClient] | None = None) -> None:
    """One heartbeat: update in-process state and (optionally) ping externally.

    Uses a short-lived httpx client for the external ping so a failure here
    can't deadlock the main app's shared client pool. Every failure mode is
    logged but never raised — the scheduler tick must not fail because a
    third-party ping URL is flaky.
    """
    _mark_heartbeat()

    ping_url = settings.healthcheck_ping_url_str
    if not ping_url:
        return

    try:
        # Short timeouts: this is a fire-and-forget ping, not a full poll
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            await client.get(ping_url)
    except Exception as e:  # noqa: BLE001 — never let a ping failure kill the tick
        logger.warning("Healthcheck ping failed: %s", e)


def update_heartbeat_gauge_continuously() -> None:
    """Refresh the Prometheus gauge with the age-in-seconds of the last
    heartbeat. Callers can invoke this from a separate APScheduler job
    (every few seconds) so the scraper sees a fresh "seconds ago" value
    without needing the heartbeat to actually tick.
    """
    SCHEDULER_LAST_HEARTBEAT_SECONDS.set(get_seconds_since_heartbeat())
