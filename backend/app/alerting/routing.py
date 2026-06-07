"""Alert routing: dedup, maintenance suppression, tier-based delivery.

The change detector produces `StatusChange` events. This module decides
for each one:

1. Is the service currently in a scheduled maintenance window?
   → Record the state transition but do not fire an alert.

2. Has this exact alert already been sent in the dedup window?
   → Skip the send but update `last_updated_at` on the existing row.

3. What tier is the service?
   → `critical` → Slack with @here mention
   → `important` → Slack without mention
   → `informational` → dashboard only, no Slack at all

Every decision is recorded to `alert_sent_log` so there's one durable
trail of "what did we tell operators and what did we suppress, why?"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite

from app.config import settings
from app.observability.metrics import ALERTS_SENT_TOTAL, ALERTS_SUPPRESSED_TOTAL
from app.poller.change_detector import StatusChange

if TYPE_CHECKING:
    from app.alerting.burn_rate import BurnRateBreach

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    """Outcome of running a StatusChange through the routing pipeline."""

    should_send: bool
    webhook_url: str | None
    channel_mention: str | None  # "<!here>" for critical tier, else None
    dedup_key: str
    tier: str
    suppressed_by: str | None  # None if sent, else reason code
    # If this change was consolidated into an aggregated upstream alert,
    # name + status of the upstream; caller suppresses the individual alert.
    aggregated_under: str | None = None


def _day_bucket(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return now.strftime("%Y-%m-%d")


def build_dedup_key(
    service_id: str,
    new_status: str,
    vendor_incident_id: str | None,
) -> str:
    """Primary key by (service_id, vendor_incident_id); fallback to
    (service_id, status, day_bucket) when no vendor ID is available.

    Never dedups on message text — vendors edit their incident titles
    mid-flight and we'd leak alerts.
    """
    if vendor_incident_id:
        return f"vendor:{service_id}:{vendor_incident_id}"
    return f"fallback:{service_id}:{new_status}:{_day_bucket()}"


async def is_in_maintenance_window(
    db: aiosqlite.Connection,
    service_id: str,
) -> bool:
    """True if the service has a scheduled_maintenances row active right now.

    Uses SQLite's own datetime() to avoid format-mismatch pitfalls: scheduled
    maintenances may be stored either as "2026-04-22 12:00:00" (from
    datetime('now', ...)) or "2026-04-22T12:00:00Z" (from vendor ISO), and
    normalizing both sides through datetime() gives a consistent comparison.
    """
    cursor = await db.execute(
        """SELECT 1 FROM scheduled_maintenances
           WHERE service_id = ?
             AND status IN ('scheduled', 'in_progress')
             AND datetime(scheduled_for) <= datetime('now')
             AND (scheduled_until IS NULL
                  OR datetime(scheduled_until) >= datetime('now'))
           LIMIT 1""",
        (service_id,),
    )
    return (await cursor.fetchone()) is not None


async def was_recently_alerted(
    db: aiosqlite.Connection,
    dedup_key: str,
    window_seconds: int,
) -> bool:
    """True if any alert with this dedup_key was sent within the window."""
    cursor = await db.execute(
        """SELECT 1 FROM alert_sent_log
           WHERE dedup_key = ?
             AND suppressed_by IS NULL
             AND first_sent_at >= datetime('now', ? || ' seconds')
           LIMIT 1""",
        (dedup_key, f"-{window_seconds}"),
    )
    return (await cursor.fetchone()) is not None


async def get_service_tier(
    db: aiosqlite.Connection,
    service_id: str,
) -> tuple[str, str | None]:
    """Return (tier, slack_channel_override) for a service."""
    cursor = await db.execute(
        "SELECT tier, slack_channel_override FROM services WHERE id = ?",
        (service_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return ("important", None)
    return (row["tier"] or "important", row["slack_channel_override"])


async def route_status_change(
    db: aiosqlite.Connection,
    change: StatusChange,
    *,
    aggregated_under: str | None = None,
    vendor_incident_id: str | None = None,
) -> RoutingDecision:
    """Run a StatusChange through the full routing pipeline.

    Decision order:
      maintenance window → dedup → tier → aggregation → fire
    """
    dedup_key = build_dedup_key(change.service_id, change.new_status, vendor_incident_id)
    tier, channel_override = await get_service_tier(db, change.service_id)

    if aggregated_under:
        return RoutingDecision(
            should_send=False,
            webhook_url=None,
            channel_mention=None,
            dedup_key=dedup_key,
            tier=tier,
            suppressed_by="aggregated_under_upstream",
            aggregated_under=aggregated_under,
        )

    if await is_in_maintenance_window(db, change.service_id):
        return RoutingDecision(
            should_send=False,
            webhook_url=None,
            channel_mention=None,
            dedup_key=dedup_key,
            tier=tier,
            suppressed_by="maintenance_window",
        )

    # Recoveries to 'operational' skip dedup — users always want to know
    # "it's back", even if they just saw the outage alert minutes ago.
    if change.new_status != "operational" and await was_recently_alerted(
        db,
        dedup_key,
        settings.alert_dedup_window_seconds,
    ):
        return RoutingDecision(
            should_send=False,
            webhook_url=None,
            channel_mention=None,
            dedup_key=dedup_key,
            tier=tier,
            suppressed_by="dedup",
        )

    if tier == "informational":
        return RoutingDecision(
            should_send=False,
            webhook_url=None,
            channel_mention=None,
            dedup_key=dedup_key,
            tier=tier,
            suppressed_by="tier_informational",
        )

    # slack_channel_override stores a full webhook URL, not a channel name —
    # Slack webhooks are bound to channels at creation, so routing to a
    # different channel requires a different webhook URL.
    webhook_url = channel_override or settings.slack_webhook_url_str
    if not webhook_url:
        return RoutingDecision(
            should_send=False,
            webhook_url=None,
            channel_mention=None,
            dedup_key=dedup_key,
            tier=tier,
            suppressed_by="webhook_not_configured",
        )

    mention = "<!here>" if tier == "critical" else None
    return RoutingDecision(
        should_send=True,
        webhook_url=webhook_url,
        channel_mention=mention,
        dedup_key=dedup_key,
        tier=tier,
        suppressed_by=None,
    )


async def record_alert(
    db: aiosqlite.Connection,
    change: StatusChange,
    decision: RoutingDecision,
    *,
    alert_kind: str = "status_change",
    slack_ts: str | None = None,
) -> None:
    """Append one row to alert_sent_log, suppressed or not.

    Writing suppressions too gives operators a full audit: why *didn't*
    we alert on this change? Set `suppressed_by` to the reason code.
    """
    await db.execute(
        """INSERT INTO alert_sent_log
           (dedup_key, service_id, status_event_id, severity, new_status,
            alert_kind, slack_channel, slack_ts, suppressed_by,
            first_sent_at, last_updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        (
            decision.dedup_key,
            change.service_id,
            change.event_id,
            decision.tier,
            change.new_status,
            alert_kind,
            None,  # slack_channel — filled when we model multiple channels
            slack_ts,
            decision.suppressed_by,
        ),
    )

    # Mirror into Prometheus so operators can scrape alert hygiene trends
    if decision.suppressed_by:
        ALERTS_SUPPRESSED_TOTAL.labels(
            kind=alert_kind,
            reason=decision.suppressed_by,
        ).inc()
    else:
        ALERTS_SENT_TOTAL.labels(
            kind=alert_kind,
            severity=decision.tier,
        ).inc()


# ── Dependency correlation ──────────────────────────────────────────

# ── SLO burn-rate routing ───────────────────────────────────────────


def build_slo_burn_rate_dedup_key(service_id: str, severity: str) -> str:
    """e.g. 'slo_burn:identity-provider:fast' — used by alert_sent_log for dedup."""
    return f"slo_burn:{service_id}:{severity}"


async def route_slo_burn_rate_alert(
    db: aiosqlite.Connection,
    breach: BurnRateBreach,
    webhook_url: str | None,
    now: datetime,
) -> RoutingDecision:
    """Decide whether to fire a burn-rate alert.

    Decision order mirrors route_status_change:
      dedup → maintenance window → webhook configured → fire
    """
    dedup_key = build_slo_burn_rate_dedup_key(breach.service_id, breach.severity)
    tier = "critical" if breach.severity == "fast" else "important"

    if await was_recently_alerted(db, dedup_key, settings.alert_dedup_window_seconds):
        return RoutingDecision(
            should_send=False,
            webhook_url=None,
            channel_mention=None,
            dedup_key=dedup_key,
            tier=tier,
            suppressed_by="dedup",
        )

    if await is_in_maintenance_window(db, breach.service_id):
        return RoutingDecision(
            should_send=False,
            webhook_url=None,
            channel_mention=None,
            dedup_key=dedup_key,
            tier=tier,
            suppressed_by="maintenance_window",
        )

    if not webhook_url:
        return RoutingDecision(
            should_send=False,
            webhook_url=None,
            channel_mention=None,
            dedup_key=dedup_key,
            tier=tier,
            suppressed_by="webhook_not_configured",
        )

    channel_mention: str | None = "<!here>" if breach.severity == "fast" else None
    return RoutingDecision(
        should_send=True,
        webhook_url=webhook_url,
        channel_mention=channel_mention,
        dedup_key=dedup_key,
        tier=tier,
        suppressed_by=None,
    )


async def record_slo_alert(
    db: aiosqlite.Connection,
    breach: BurnRateBreach,
    decision: RoutingDecision,
) -> None:
    """Append one row to alert_sent_log for a burn-rate breach.

    Parallel to record_alert but accepts a BurnRateBreach instead of a
    StatusChange (SLO alerts are not tied to a status_events row).
    """
    await db.execute(
        """INSERT INTO alert_sent_log
           (dedup_key, service_id, status_event_id, severity, new_status,
            alert_kind, slack_channel, slack_ts, suppressed_by,
            first_sent_at, last_updated_at)
           VALUES (?, ?, NULL, ?, ?, ?, NULL, NULL, ?,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        (
            decision.dedup_key,
            breach.service_id,
            decision.tier,
            f"slo_{breach.severity}_burn",
            "slo_burn_rate",
            decision.suppressed_by,
        ),
    )

    if decision.suppressed_by:
        ALERTS_SUPPRESSED_TOTAL.labels(
            kind="slo_burn_rate",
            reason=decision.suppressed_by,
        ).inc()
    else:
        ALERTS_SENT_TOTAL.labels(
            kind="slo_burn_rate",
            severity=decision.tier,
        ).inc()


# ── Dependency correlation ──────────────────────────────────────────


async def find_aggregation_candidates(
    db: aiosqlite.Connection,
    changes: list[StatusChange],
    threshold: int,
) -> dict[str, list[StatusChange]]:
    """Group downstream changes under their upstream when correlation fires.

    If an upstream service transitions away from `operational` and it has
    at least `threshold` downstream services in this batch that are also
    transitioning away from `operational`, those downstream changes should
    be consolidated into a single aggregated alert about the upstream.

    Returns a dict {upstream_service_id: [downstream StatusChange, ...]}.
    The upstream's own StatusChange stays separate so the caller can render
    it as the parent message and cite the dependents.
    """
    if not changes:
        return {}

    # Build quick lookup: which service_ids in this batch are going non-operational?
    affected_ids = {
        c.service_id
        for c in changes
        if c.new_status != "operational" and c.previous_status == "operational"
    }
    if not affected_ids:
        return {}

    grouped: dict[str, list[StatusChange]] = {}

    # For each non-operational upstream in this batch, look up its declared
    # downstream services and count how many are also affected right now.
    for upstream_change in changes:
        if upstream_change.new_status == "operational":
            continue
        if upstream_change.previous_status != "operational":
            continue

        cursor = await db.execute(
            """SELECT downstream_service_id
               FROM service_dependencies
               WHERE upstream_service_id = ?""",
            (upstream_change.service_id,),
        )
        declared_downstream = {row[0] for row in await cursor.fetchall()}

        consolidated = [
            c
            for c in changes
            if c.service_id != upstream_change.service_id
            and c.service_id in declared_downstream
            and c.service_id in affected_ids
        ]

        if len(consolidated) >= threshold:
            grouped[upstream_change.service_id] = consolidated

    return grouped
