"""Alerting engine: orchestrates impact statement generation and Slack notifications.

Called after detect_changes() in the poll cycle and after manual status updates.
"""

import asyncio
import logging

import aiosqlite
import httpx

from app.alerting.slack import build_batch_slack_alert, build_slack_alert, send_slack_alert
from app.alerting.templates import generate_impact_statement
from app.config import settings
from app.dependencies.graph import get_downstream
from app.poller.change_detector import StatusChange

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

        # Collect Slack alert data (suppress boot warmup and active maintenance windows)
        if not is_boot_warmup:
            # Check for active maintenance — suppress alerts for services under maintenance
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
                logger.info("Suppressing alert for %s — active maintenance window", change.service_display_name)
            else:
                alert_data.append((
                    change.service_display_name,
                    change.previous_status,
                    change.new_status,
                    impact,
                    change.status_page_url,
                ))

    # Send Slack alerts
    if not alert_data or not settings.slack_webhook_url:
        if alert_data:
            logger.debug("Slack webhook not configured, skipping %d alert(s)", len(alert_data))
        return

    try:
        if len(alert_data) > BATCH_THRESHOLD:
            payload = build_batch_slack_alert(alert_data)
            success = await send_slack_alert(
                settings.slack_webhook_url, payload, client=http_client,
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
                    settings.slack_webhook_url, payload, client=http_client,
                )
                if success:
                    logger.info("Sent Slack alert for %s", name)
                else:
                    logger.warning("Failed to send Slack alert for %s", name)
    except Exception:
        logger.exception("Slack alerting failed")
