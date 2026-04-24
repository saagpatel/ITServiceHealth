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
from datetime import UTC

import aiosqlite
import httpx

from app.alerting.routing import (
    find_aggregation_candidates,
    record_alert,
    route_status_change,
)
from app.alerting.slack import (
    build_aggregated_upstream_alert,
    build_batch_slack_alert,
    build_poller_health_alert,
    build_slack_alert,
    send_slack_alert,
)
from app.alerting.templates import generate_impact_statement
from app.config import settings
from app.dependencies.graph import get_downstream
from app.observability.metrics import ALERTS_SENT_TOTAL
from app.poller.change_detector import PollerHealthChange, StatusChange

logger = logging.getLogger(__name__)

BATCH_THRESHOLD = 3


async def process_changes(
    db: aiosqlite.Connection,
    write_lock: asyncio.Lock,
    changes: list[StatusChange],
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Process status changes: generate impact statements, route, and alert.

    Pipeline per change:
      1. Generate impact statement (dependency graph + templates).
      2. Write impact_statement back to the status_events row.
      3. Generate an incident report on recovery.
      4. Route through `alert_sent_log` (maintenance, dedup, tier).
      5. If upstream-down caused >= N dependents to flip, consolidate
         their individual alerts into one aggregated upstream alert.
      6. Send the Slack payload with the appropriate mention (@here for
         critical tier, no mention otherwise).
    """
    if not changes:
        return

    # Dependency correlation: group downstream changes under upstream
    # parent changes when the configured threshold is met.
    aggregation = await find_aggregation_candidates(
        db, changes, threshold=settings.dependency_correlation_threshold,
    )
    aggregated_under: dict[str, str] = {}
    for upstream_id, dependents in aggregation.items():
        upstream_change = next(c for c in changes if c.service_id == upstream_id)
        for dep in dependents:
            aggregated_under[dep.service_id] = upstream_change.service_display_name

    # Generate + persist impact statements + incident reports
    impact_by_service: dict[str, str] = {}
    for change in changes:
        try:
            downstream = await get_downstream(db, change.service_id)
            impact = generate_impact_statement(change, downstream)
        except Exception:
            logger.exception("Failed to generate impact for %s", change.service_id)
            impact = f"{change.service_display_name} status changed."
        impact_by_service[change.service_id] = impact

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

        is_boot_warmup = (
            change.previous_status == "unknown"
            and change.new_status == "operational"
        )
        if change.new_status == "operational" and not is_boot_warmup:
            try:
                from datetime import datetime

                from app.reports import generate_incident_report
                resolved_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                report = await generate_incident_report(db, write_lock, change.service_id, resolved_at)
                if settings.postmortems_enabled and report:
                    try:
                        from pathlib import Path

                        from app.postmortems import write_postmortem
                        out_dir = Path(settings.postmortems_dir).resolve()
                        written = await write_postmortem(report, out_dir=out_dir)
                        if written:
                            logger.info("Wrote postmortem draft: %s", written)
                    except Exception:
                        logger.exception(
                            "Failed to write postmortem for %s", change.service_id,
                        )
            except Exception:
                logger.exception("Failed to generate incident report for %s", change.service_id)

    # Route every change; suppressed alerts still record to alert_sent_log
    # so operators can audit "why didn't we alert on X?".
    # Tuple: (change, channel_mention, dedup_key)
    individual_sends: list[tuple[StatusChange, str, str]] = []
    for change in changes:
        is_boot_warmup = (
            change.previous_status == "unknown"
            and change.new_status == "operational"
        )
        if is_boot_warmup:
            # Still record the state transition, but don't alert — a service
            # resolving from unknown to operational just means the poller
            # warmed up; it's not real news.
            continue

        decision = await route_status_change(
            db, change,
            aggregated_under=aggregated_under.get(change.service_id),
            vendor_incident_id=change.vendor_incident_id,
        )
        async with write_lock:
            await record_alert(db, change, decision)
            await db.commit()

        if decision.suppressed_by:
            logger.info(
                "Suppressed alert for %s (%s → %s): %s",
                change.service_display_name,
                change.previous_status, change.new_status,
                decision.suppressed_by,
            )
            continue
        individual_sends.append((change, decision.channel_mention or "", decision.dedup_key))

    # Build aggregated upstream messages (one per upstream with >= threshold dependents)
    aggregated_payloads: list[tuple[str, dict]] = []
    for upstream_id, dependents in aggregation.items():
        upstream_change = next(c for c in changes if c.service_id == upstream_id)
        decision = await route_status_change(
            db, upstream_change,
            vendor_incident_id=upstream_change.vendor_incident_id,
        )
        async with write_lock:
            await record_alert(
                db, upstream_change, decision, alert_kind="aggregated_upstream",
            )
            await db.commit()

        if decision.suppressed_by:
            # Upstream itself is suppressed (tier/maintenance/dedup/webhook).
            # Don't emit aggregated either — but individual dependents are
            # still suppressed via aggregated_under to avoid a flood. This
            # is the right behavior: if the upstream isn't worth alerting
            # on, neither are its N dependents saying the same thing.
            logger.info(
                "Aggregated alert for %s suppressed (%s); %d dependents also silenced",
                upstream_change.service_display_name,
                decision.suppressed_by, len(dependents),
            )
            continue

        payload = build_aggregated_upstream_alert(
            upstream_change=upstream_change,
            dependents=dependents,
            impact_statement=impact_by_service.get(upstream_id, ""),
            mention=decision.channel_mention,
            dedup_key=decision.dedup_key,
        )
        aggregated_payloads.append((decision.webhook_url, payload))

    # Send aggregated payloads first (they're the headline news)
    for webhook_url, payload in aggregated_payloads:
        try:
            ok = await send_slack_alert(webhook_url, payload, client=http_client)
            if ok:
                logger.info("Sent aggregated upstream alert")
            else:
                logger.warning("Failed to send aggregated upstream alert")
        except Exception:
            logger.exception("Aggregated alert send failed")
        await asyncio.sleep(1.0)

    # Send individual alerts — either via batch (>3) or one-by-one
    if not individual_sends:
        return

    webhook_url = settings.slack_webhook_url_str
    if not webhook_url:
        return

    try:
        if len(individual_sends) > BATCH_THRESHOLD:
            alert_data = [
                (
                    c.service_display_name,
                    c.previous_status,
                    c.new_status,
                    impact_by_service.get(c.service_id, ""),
                    c.status_page_url,
                )
                for c, _mention, _dedup in individual_sends
            ]
            payload = build_batch_slack_alert(alert_data)
            ok = await send_slack_alert(webhook_url, payload, client=http_client)
            if ok:
                logger.info("Sent batch Slack alert for %d changes", len(individual_sends))
            else:
                logger.warning("Failed to send batch Slack alert")
        else:
            for i, (change, mention, dedup_key) in enumerate(individual_sends):
                if i > 0:
                    await asyncio.sleep(1.0)
                payload = build_slack_alert(
                    change.service_display_name,
                    change.previous_status,
                    change.new_status,
                    impact_by_service.get(change.service_id, ""),
                    change.status_page_url,
                    mention=mention or None,
                    dedup_key=dedup_key,
                )
                ok = await send_slack_alert(webhook_url, payload, client=http_client)
                if ok:
                    logger.info("Sent Slack alert for %s", change.service_display_name)
                else:
                    logger.warning(
                        "Failed to send Slack alert for %s", change.service_display_name,
                    )
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
                ALERTS_SENT_TOTAL.labels(
                    kind="poller_health", severity=hc.new_health,
                ).inc()
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
