"""Alerting engine: orchestrates impact statement generation and Slack notifications.

Called after detect_changes() in the poll cycle and after manual status updates.

Alert fatigue prevention:
- Debounce: degraded/partial_outage must persist for 2+ poll cycles (120s) before alerting.
  If the service recovers within the debounce window, zero alerts are sent.
- Immediate: major_outage bypasses debounce and alerts instantly.
- Cascade grouping: when multiple services recover simultaneously and share an upstream
  dependency, they are grouped into a single "X recovered, N downstream restored" message.
- Boot warmup suppression: unknown→operational transitions are never alerted.
- Maintenance suppression: services with active maintenance windows are not alerted.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite
import httpx

from app.alerting.slack import (
    build_batch_slack_alert,
    build_cascade_recovery_alert,
    build_slack_alert,
    send_slack_alert,
)
from app.alerting.templates import generate_impact_statement
from app.config import settings
from app.dependencies.graph import get_downstream, get_upstream
from app.poller.change_detector import StatusChange

logger = logging.getLogger(__name__)

BATCH_THRESHOLD = 3
DEBOUNCE_SECONDS = 120  # 2 poll cycles at 60s interval
IMMEDIATE_STATUSES = {"major_outage"}


@dataclass
class PendingAlert:
    """A status change waiting out its debounce window."""

    change: StatusChange
    first_seen: datetime
    impact: str


# Module-level debounce state: service_id → PendingAlert
_pending_alerts: dict[str, PendingAlert] = {}


def flush_matured_alerts() -> list[tuple[str, str, str, str, str | None]]:
    """Return alerts that have aged past the debounce window. Removes them from pending."""
    now = datetime.now(timezone.utc)
    matured: list[tuple[str, str, str, str, str | None]] = []
    expired_keys: list[str] = []

    for service_id, pending in _pending_alerts.items():
        age = (now - pending.first_seen).total_seconds()
        if age >= DEBOUNCE_SECONDS:
            c = pending.change
            matured.append((
                c.service_display_name,
                c.previous_status,
                c.new_status,
                pending.impact,
                c.status_page_url,
            ))
            expired_keys.append(service_id)
            logger.info(
                "Debounce matured for %s (%s) after %ds",
                c.service_display_name, c.new_status, int(age),
            )

    for key in expired_keys:
        del _pending_alerts[key]

    return matured


async def group_cascade_recoveries(
    db: aiosqlite.Connection,
    recoveries: list[tuple[str, str, str, str, str | None]],
) -> tuple[list[tuple[str, str, str, str, str | None]], list[dict]]:
    """Group recovery alerts that share an upstream dependency.

    Returns (individual_alerts, grouped_alerts) where grouped_alerts are dicts
    with upstream_name and downstream_names for the cascade message builder.
    """
    if len(recoveries) < 2:
        return recoveries, []

    # Map service names to find upstream dependencies
    # Build: upstream_name → [list of recovering service names]
    recovering_names = {name for name, _, _, _, _ in recoveries}
    upstream_groups: dict[str, list[str]] = {}  # upstream_name → downstream names

    for name, old, new, impact, url in recoveries:
        # Find this service's upstream deps
        # We need service_id but only have name — query DB
        cursor = await db.execute(
            "SELECT id FROM services WHERE display_name = ?", (name,)
        )
        row = await cursor.fetchone()
        if not row:
            continue

        upstreams = await get_upstream(db, row[0])
        for up in upstreams:
            up_name = up["service_name"]
            if up_name in recovering_names and up_name != name:
                if up_name not in upstream_groups:
                    upstream_groups[up_name] = []
                upstream_groups[up_name].append(name)

    # Only group if upstream has 2+ downstream recoveries
    grouped_downstreams: set[str] = set()
    grouped_alerts: list[dict] = []

    for upstream_name, downstream_names in upstream_groups.items():
        if len(downstream_names) >= 2:
            grouped_alerts.append({
                "upstream_name": upstream_name,
                "downstream_names": downstream_names,
            })
            grouped_downstreams.update(downstream_names)
            grouped_downstreams.add(upstream_name)

    # Individual recoveries = those not part of any cascade group
    individual = [
        r for r in recoveries if r[0] not in grouped_downstreams
    ]

    return individual, grouped_alerts


async def process_changes(
    db: aiosqlite.Connection,
    write_lock: asyncio.Lock,
    changes: list[StatusChange],
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Process status changes: generate impact statements, update DB, send Slack alerts.

    Two-phase alerting:
    Phase A: For each change, generate impact, write to DB, classify into alert buckets.
    Phase B: Flush matured debounce alerts, apply cascade grouping, send all alerts.
    """
    if not changes:
        return

    immediate_alerts: list[tuple[str, str, str, str, str | None]] = []
    recovery_alerts: list[tuple[str, str, str, str, str | None]] = []

    # ── Phase A: Process each change ──────────────────────────────────

    for change in changes:
        # Generate impact statement
        try:
            downstream = await get_downstream(db, change.service_id)
            impact = generate_impact_statement(change, downstream)
        except Exception:
            logger.exception("Failed to generate impact for %s", change.service_id)
            impact = f"{change.service_display_name} status changed."

        # Write impact_statement to status_events
        try:
            async with write_lock:
                if change.event_id:
                    await db.execute(
                        "UPDATE status_events SET impact_statement = ? WHERE id = ?",
                        (impact, change.event_id),
                    )
                else:
                    await db.execute(
                        """UPDATE status_events SET impact_statement = ?
                           WHERE id = (
                               SELECT id FROM status_events
                               WHERE service_id = ?
                               ORDER BY created_at DESC LIMIT 1
                           )""",
                        (impact, change.service_id),
                    )
                await db.commit()
        except Exception:
            logger.exception("Failed to write impact_statement for %s", change.service_id)

        # Generate incident report on recovery (non-boot)
        is_boot_warmup = (
            change.previous_status == "unknown"
            and change.new_status == "operational"
        )
        if change.new_status == "operational" and not is_boot_warmup:
            try:
                from app.reports import generate_incident_report

                resolved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                await generate_incident_report(db, write_lock, change.service_id, resolved_at)
            except Exception:
                logger.exception("Failed to generate incident report for %s", change.service_id)

        # ── Classify into alert buckets ───────────────────────────────
        if is_boot_warmup:
            continue

        # Check maintenance suppression
        in_maintenance = False
        try:
            cursor = await db.execute(
                """SELECT 1 FROM scheduled_maintenances
                   WHERE service_id = ? AND status IN ('in_progress', 'verifying')
                   LIMIT 1""",
                (change.service_id,),
            )
            in_maintenance = await cursor.fetchone() is not None
        except Exception:
            logger.debug("Failed to check maintenance status for %s", change.service_id)

        if in_maintenance:
            logger.info(
                "Suppressing alert for %s — active maintenance window",
                change.service_display_name,
            )
            continue

        alert_tuple = (
            change.service_display_name,
            change.previous_status,
            change.new_status,
            impact,
            change.status_page_url,
        )

        # Immediate: major_outage bypasses debounce
        if change.new_status in IMMEDIATE_STATUSES:
            # Clear any pending debounce for this service (it escalated)
            _pending_alerts.pop(change.service_id, None)
            immediate_alerts.append(alert_tuple)

        # Recovery: check if this cancels a pending debounce (flap suppression)
        elif change.new_status == "operational":
            if change.service_id in _pending_alerts:
                pending = _pending_alerts.pop(change.service_id)
                logger.info(
                    "Flap suppressed for %s — recovered within debounce window (%s → %s → operational)",
                    change.service_display_name,
                    pending.change.previous_status,
                    pending.change.new_status,
                )
            else:
                recovery_alerts.append(alert_tuple)

        # Degradation: enter debounce queue
        elif change.new_status in ("degraded", "partial_outage"):
            if change.service_id not in _pending_alerts:
                _pending_alerts[change.service_id] = PendingAlert(
                    change=change,
                    first_seen=datetime.now(timezone.utc),
                    impact=impact,
                )
                logger.debug(
                    "Debounce started for %s (%s)",
                    change.service_display_name, change.new_status,
                )

    # ── Phase B: Flush matured + cascade group + send ─────────────────

    matured_alerts = flush_matured_alerts()

    # Apply cascade grouping to recoveries
    individual_recoveries, cascade_groups = await group_cascade_recoveries(
        db, recovery_alerts,
    )

    # Combine all alerts to send
    all_alerts = immediate_alerts + matured_alerts + individual_recoveries

    # Send alerts
    if not settings.slack_webhook_url:
        total = len(all_alerts) + len(cascade_groups)
        if total:
            logger.debug("Slack webhook not configured, skipping %d alert(s)", total)
        return

    try:
        # Send cascade recovery messages
        for group in cascade_groups:
            payload = build_cascade_recovery_alert(
                group["upstream_name"], group["downstream_names"],
            )
            success = await send_slack_alert(
                settings.slack_webhook_url, payload, client=http_client,
            )
            if success:
                logger.info(
                    "Sent cascade recovery alert: %s + %d downstream",
                    group["upstream_name"], len(group["downstream_names"]),
                )
            else:
                logger.warning("Failed to send cascade recovery alert for %s", group["upstream_name"])

        # Send regular alerts
        if all_alerts:
            if len(all_alerts) > BATCH_THRESHOLD:
                payload = build_batch_slack_alert(all_alerts)
                success = await send_slack_alert(
                    settings.slack_webhook_url, payload, client=http_client,
                )
                if success:
                    logger.info("Sent batch Slack alert for %d changes", len(all_alerts))
                else:
                    logger.warning("Failed to send batch Slack alert")
            else:
                for i, (name, old, new, impact, url) in enumerate(all_alerts):
                    if i > 0:
                        await asyncio.sleep(1.0)
                    payload = build_slack_alert(name, old, new, impact, url)
                    success = await send_slack_alert(
                        settings.slack_webhook_url, payload, client=http_client,
                    )
                    if success:
                        logger.info("Sent Slack alert for %s", name)
                    else:
                        logger.warning("Failed to send Slack alert for %s", name)
    except Exception:
        logger.exception("Slack alerting failed")
