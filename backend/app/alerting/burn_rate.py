"""Multi-burn-rate SLO alerting.

Evaluates each service against Google SRE-style fast and slow burn-rate
thresholds on every scheduled cycle. A "burn rate" answers: "at the current
failure rate, how quickly are we draining our error budget compared to what
is allowable for the target SLO?"

Fast breach  (14.4x default): short impact, high urgency - page immediately.
Slow breach  (6.0x default):  sustained burn without immediate triage risk
             - important but not PagerDuty-at-3am.

The cycle is gated by `settings.slo_burn_rate_enabled` (default False).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import aiosqlite
import structlog

from app.config import settings
from app.sla import compute_error_budget_remaining, compute_uptime

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BurnRateBreach:
    """A detected SLO burn-rate violation for a single service."""

    service_id: str
    service_name: str
    severity: Literal["fast", "slow"]
    long_window_burn_rate: float   # e.g. 14.4 = consuming budget at 14.4x the allowable rate
    short_window_burn_rate: float
    error_budget_remaining_pct: float  # 0-100
    long_window_label: str   # "1h" or "6h"
    short_window_label: str  # "5m" or "30m"


def _burn_rate(uptime_pct: float | None, allowable_failure_rate: float) -> float | None:
    """Compute burn rate from an uptime percentage.

    Returns None when the window has no tracked data (unknown-dominated),
    0.0 when the service was perfectly operational, or a positive multiplier
    representing how many times the allowable failure rate is being consumed.
    """
    if uptime_pct is None:
        return None
    if uptime_pct >= 100.0:
        return 0.0
    failure_rate = (100.0 - uptime_pct) / 100.0
    return failure_rate / allowable_failure_rate


async def evaluate_burn_rate(
    db: aiosqlite.Connection,
    service_id: str,
    service_name: str,
    now: datetime,
) -> list[BurnRateBreach]:
    """Evaluate burn-rate breaches for a single service at `now`.

    Calls compute_uptime for 5m, 30m, 1h, 6h, and 30d windows. Returns up
    to two BurnRateBreach items (one fast, one slow) if thresholds are exceeded.

    Nulls (unknown-dominated windows) never trigger a breach.
    """
    from datetime import timedelta

    structlog.contextvars.bind_contextvars(
        slo_alert_type="burn_rate",
        slo_service_id=service_id,
    )

    slo_target = settings.slo_target_percent
    allowable_failure_rate = (100.0 - slo_target) / 100.0

    try:
        w5m  = await compute_uptime(db, service_id, now - timedelta(minutes=5),  now)
        w30m = await compute_uptime(db, service_id, now - timedelta(minutes=30), now)
        w1h  = await compute_uptime(db, service_id, now - timedelta(hours=1),   now)
        w6h  = await compute_uptime(db, service_id, now - timedelta(hours=6),   now)
        w30d = await compute_uptime(db, service_id, now - timedelta(days=30),   now)
    except Exception:
        logger.exception(
            "compute_uptime failed for service %s — skipping breach evaluation",
            service_id,
        )
        return []

    # Error budget remaining over the 30-day rolling window
    error_budget_remaining_pct = compute_error_budget_remaining(
        w30d.uptime_percent, slo_target,
    )

    br_5m  = _burn_rate(w5m.uptime_percent,  allowable_failure_rate)
    br_30m = _burn_rate(w30m.uptime_percent, allowable_failure_rate)
    br_1h  = _burn_rate(w1h.uptime_percent,  allowable_failure_rate)
    br_6h  = _burn_rate(w6h.uptime_percent,  allowable_failure_rate)

    breaches: list[BurnRateBreach] = []

    fast_threshold = settings.slo_burn_rate_fast_threshold
    if (
        br_5m is not None
        and br_1h is not None
        and br_5m >= fast_threshold
        and br_1h >= fast_threshold
    ):
        breaches.append(BurnRateBreach(
            service_id=service_id,
            service_name=service_name,
            severity="fast",
            long_window_burn_rate=br_1h,
            short_window_burn_rate=br_5m,
            error_budget_remaining_pct=error_budget_remaining_pct,
            long_window_label="1h",
            short_window_label="5m",
        ))

    slow_threshold = settings.slo_burn_rate_slow_threshold
    if (
        br_30m is not None
        and br_6h is not None
        and br_30m >= slow_threshold
        and br_6h >= slow_threshold
    ):
        breaches.append(BurnRateBreach(
            service_id=service_id,
            service_name=service_name,
            severity="slow",
            long_window_burn_rate=br_6h,
            short_window_burn_rate=br_30m,
            error_budget_remaining_pct=error_budget_remaining_pct,
            long_window_label="6h",
            short_window_label="30m",
        ))

    return breaches


async def run_slo_burn_rate_cycle(app: FastAPI) -> None:
    """Run one full SLO burn-rate evaluation across all services.

    Guard: returns immediately when `settings.slo_burn_rate_enabled` is False.

    For each service, calls evaluate_burn_rate → route_slo_burn_rate_alert →
    send_slack_alert + record_slo_alert. Logs a summary at the end and warns
    when the cycle itself takes longer than 5 seconds.
    """
    if not settings.slo_burn_rate_enabled:
        return

    cycle_id = uuid.uuid4().hex[:12]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(slo_cycle_id=cycle_id)

    cycle_start = datetime.now(UTC)

    # Deferred imports to avoid circular-import risk at module load time
    from app.alerting.routing import record_slo_alert, route_slo_burn_rate_alert
    from app.alerting.slack import build_slo_burn_rate_alert, send_slack_alert
    from app.database import get_db

    db = await get_db()

    try:
        cursor = await db.execute("SELECT id, display_name FROM services")
        services = await cursor.fetchall()
    except Exception:
        logger.exception("slo_burn_rate_cycle: failed to query services table")
        return

    now = datetime.now(UTC)
    webhook_url: str | None = settings.slack_webhook_url_str

    total_evaluated = 0
    total_breaches  = 0
    total_sent      = 0
    total_suppressed = 0

    for row in services:
        service_id: str   = row[0]
        service_name: str = row[1]
        total_evaluated += 1

        breaches = await evaluate_burn_rate(db, service_id, service_name, now)
        total_breaches += len(breaches)

        for breach in breaches:
            decision = await route_slo_burn_rate_alert(db, breach, webhook_url, now)

            await record_slo_alert(db, breach, decision)
            try:
                await db.commit()
            except Exception:
                logger.exception(
                    "slo_burn_rate_cycle: failed to commit alert record for %s/%s",
                    service_id, breach.severity,
                )

            if decision.suppressed_by:
                total_suppressed += 1
                logger.info(
                    "SLO burn-rate alert suppressed: service=%s severity=%s reason=%s",
                    service_id, breach.severity, decision.suppressed_by,
                )
                continue

            # decision.should_send is True — fire the Slack alert
            payload = build_slo_burn_rate_alert(
                breach,
                channel_mention=decision.channel_mention or "",
                dedup_key=decision.dedup_key,
                status_page_url=None,   # no per-service status_page_url on SLO alerts
            )
            ok = await send_slack_alert(decision.webhook_url or "", payload)  # type: ignore[arg-type]
            if ok:
                total_sent += 1
                logger.info(
                    "SLO burn-rate alert sent: service=%s severity=%s "
                    "long_br=%.1f short_br=%.1f budget_remaining=%.1f%%",
                    service_id, breach.severity,
                    breach.long_window_burn_rate, breach.short_window_burn_rate,
                    breach.error_budget_remaining_pct,
                )
            else:
                logger.warning(
                    "SLO burn-rate alert send failed: service=%s severity=%s",
                    service_id, breach.severity,
                )

    elapsed = (datetime.now(UTC) - cycle_start).total_seconds()

    if elapsed > 5.0:
        logger.warning(
            "SLO burn-rate cycle took %.1fs (>5s): evaluated=%d breaches=%d "
            "sent=%d suppressed=%d",
            elapsed, total_evaluated, total_breaches, total_sent, total_suppressed,
        )
    else:
        logger.info(
            "SLO burn-rate cycle complete in %.1fs: evaluated=%d breaches=%d "
            "sent=%d suppressed=%d",
            elapsed, total_evaluated, total_breaches, total_sent, total_suppressed,
        )

    structlog.contextvars.clear_contextvars()
