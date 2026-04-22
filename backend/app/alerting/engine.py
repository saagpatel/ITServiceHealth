"""Alerting engine: orchestrates impact statement generation and Slack notifications.

Called after detect_changes() in the poll cycle and after manual status updates.
Handles two distinct alert channels:

- **Vendor-outage alerts** (`process_changes`): a service the IT team cares
  about changed status. Routed to the primary Slack webhook.
- **Poller-health alerts** (`process_poller_health_changes`): *our* poller
  is broken or recovered. Routed to a separate webhook so responders can
  tell "we're blind" from "vendor is down" at a glance. Falls back to the
  primary webhook when the dedicated one is not configured, but tags the
  message as poller-health so it's never mistaken for a vendor outage.
"""

import asyncio
import logging

import aiosqlite
import httpx

from app.alerting.slack import (
    build_batch_slack_alert,
    build_poller_health_alert,
    build_slack_alert,
    send_slack_alert,
)
from app.alerting.templates import generate_impact_statement
from app.config import settings
from app.dependencies.graph import get_downstream
from app.poller.change_detector import PollerHealthChange, StatusChange

logger = logging.getLogger(__name__)

BATCH_THRESHOLD = 3


async def process_changes(
    db: aiosqlite.Connection,
    write_lock: asyncio.Lock,
    changes: list[StatusChange],
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Process status changes: generate impact statements, update DB, send Slack alerts.

    For each change:
    1. Query downstream impacts
    2. Generate impact statement
    3. Write impact_statement to the status_events row

    Then send Slack alerts (if webhook configured):
    - 1-3 changes: individual messages with 1s delay
    - >3 changes: single batch message
    - Suppress: skip Slack for unknown→operational (boot warmup)
    """
    if not changes:
        return

    alert_data: list[tuple[str, str, str, str, str | None]] = []

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
                    # Fallback: update most recent event for this service
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
                from datetime import datetime, timezone
                resolved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                await generate_incident_report(db, write_lock, change.service_id, resolved_at)
            except Exception:
                logger.exception("Failed to generate incident report for %s", change.service_id)

        # Collect Slack alert data (suppress boot warmup: unknown→operational)
        if not is_boot_warmup:
            alert_data.append((
                change.service_display_name,
                change.previous_status,
                change.new_status,
                impact,
                change.status_page_url,
            ))

    # Send Slack alerts
    webhook_url = settings.slack_webhook_url_str
    if not alert_data or not webhook_url:
        if alert_data:
            logger.debug("Slack webhook not configured, skipping %d alert(s)", len(alert_data))
        return

    try:
        if len(alert_data) > BATCH_THRESHOLD:
            payload = build_batch_slack_alert(alert_data)
            success = await send_slack_alert(
                webhook_url, payload, client=http_client,
            )
            if success:
                logger.info("Sent batch Slack alert for %d changes", len(alert_data))
            else:
                logger.warning("Failed to send batch Slack alert")
        else:
            for i, (name, old, new, impact, url) in enumerate(alert_data):
                if i > 0:
                    await asyncio.sleep(1.0)
                payload = build_slack_alert(name, old, new, impact, url)
                success = await send_slack_alert(
                    webhook_url, payload, client=http_client,
                )
                if success:
                    logger.info("Sent Slack alert for %s", name)
                else:
                    logger.warning("Failed to send Slack alert for %s", name)
    except Exception:
        logger.exception("Slack alerting failed")


async def process_poller_health_changes(
    health_changes: list[PollerHealthChange],
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Send poller-health alerts to the dedicated webhook (falls back to main).

    These alerts answer: "is our dashboard telling the truth right now?"
    A poller-health alert fires when a service's poller flips to `broken`
    (we've been unable to reach the vendor for N consecutive cycles) or
    recovers from broken back to healthy.

    The payload is tagged as poller-health so the message is never confused
    with a vendor-outage alert, even when both channels point to the same
    Slack room in small deployments.
    """
    if not health_changes:
        return

    webhook_url = (
        settings.poller_health_slack_webhook_url_str
        or settings.slack_webhook_url_str
    )
    if not webhook_url:
        logger.debug(
            "No webhook configured, skipping %d poller-health alert(s)",
            len(health_changes),
        )
        return

    using_fallback = (
        settings.poller_health_slack_webhook_url_str is None
        and settings.slack_webhook_url_str is not None
    )

    for i, hc in enumerate(health_changes):
        if i > 0:
            await asyncio.sleep(1.0)
        payload = build_poller_health_alert(hc, using_fallback=using_fallback)
        try:
            success = await send_slack_alert(
                webhook_url, payload, client=http_client,
            )
            if success:
                logger.info(
                    "Sent poller-health alert: %s %s → %s",
                    hc.service_display_name,
                    hc.previous_health,
                    hc.new_health,
                )
            else:
                logger.warning(
                    "Failed to send poller-health alert for %s",
                    hc.service_display_name,
                )
        except Exception:
            logger.exception(
                "Poller-health alert failed for %s", hc.service_display_name,
            )
