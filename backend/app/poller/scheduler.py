"""Poll scheduler: runs all pollers on a 60-second cycle via APScheduler.

Orchestrates statuspage, Slack, and Google pollers, feeds results through
the change detector, and logs status changes.
"""

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import get_db, get_write_lock

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


def start_scheduler(app) -> None:
    """Start the poll scheduler with immediate first run."""
    scheduler.add_job(
        run_poll_cycle,
        "interval",
        seconds=settings.poll_interval_seconds,
        args=[app],
        id="poll_cycle",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.start()
    logger.info("Poll scheduler started (interval=%ds)", settings.poll_interval_seconds)


def stop_scheduler() -> None:
    """Stop the poll scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Poll scheduler stopped")


async def run_poll_cycle(app) -> None:
    """Execute one full poll cycle across all automated services."""
    try:
        client = app.state.http_client
        db = await get_db()
        write_lock = get_write_lock()

        # Load all pollable services from DB
        cursor = await db.execute(
            """SELECT id, poll_type, poll_url, statuspage_component_name,
                      current_status, display_name, status_page_url
               FROM services WHERE poll_type != 'manual'"""
        )
        rows = await cursor.fetchall()
        services_by_type: dict[str, list[dict]] = {}
        for row in rows:
            svc = dict(row)
            services_by_type.setdefault(svc["poll_type"], []).append(svc)

        # Dispatch all poller groups concurrently
        from app.poller.statuspage_poller import poll_all_statuspage
        from app.poller.slack_poller import poll_slack
        from app.poller.google_poller import poll_google
        from app.poller.salesforce_poller import poll_salesforce
        from app.poller.zendesk_poller import poll_zendesk
        from app.poller.ringcentral_poller import poll_ringcentral

        tasks = []
        task_labels = []

        statuspage_svcs = services_by_type.get("statuspage_json", [])
        if statuspage_svcs:
            tasks.append(poll_all_statuspage(client, statuspage_svcs))
            task_labels.append(f"statuspage ({len(statuspage_svcs)} services)")

        slack_svcs = services_by_type.get("slack_api", [])
        if slack_svcs:
            svc = slack_svcs[0]

            async def _poll_slack():
                result = await poll_slack(client, svc["poll_url"])
                return [(svc["id"], result)]

            tasks.append(_poll_slack())
            task_labels.append("slack (1 service)")

        google_svcs = services_by_type.get("google_json", [])
        if google_svcs:
            url = google_svcs[0]["poll_url"]
            tasks.append(poll_google(client, url, google_svcs))
            task_labels.append(f"google ({len(google_svcs)} services)")

        # Single-service custom pollers
        for poll_type, poller_fn in [
            ("salesforce_trust", poll_salesforce),
            ("zendesk_api", poll_zendesk),
            ("ringcentral_api", poll_ringcentral),
        ]:
            for svc in services_by_type.get(poll_type, []):
                async def _poll_single(s=svc, fn=poller_fn):
                    result = await fn(client, s["poll_url"])
                    return [(s["id"], result)]
                tasks.append(_poll_single())
                task_labels.append(f"{poll_type} ({svc['id']})")

        if not tasks:
            logger.warning("No pollable services found")
            return

        # Run all pollers concurrently
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten results
        all_results: list[tuple[str, ...]] = []
        for i, result in enumerate(gathered):
            if isinstance(result, Exception):
                logger.error("Poller group '%s' failed: %s", task_labels[i], result)
            else:
                all_results.extend(result)

        # Run change detection
        from app.poller.change_detector import detect_changes

        changes = await detect_changes(db, write_lock, all_results)

        # Process changes: impact statements + Slack alerts
        if changes:
            from app.alerting.engine import process_changes
            await process_changes(db, write_lock, changes, http_client=client)

        # Log summary
        logger.info(
            "Poll cycle complete: %d services polled, %d changes detected",
            len(all_results), len(changes),
        )
        for change in changes:
            logger.info(
                "  %s: %s → %s",
                change.service_display_name,
                change.previous_status,
                change.new_status,
            )

    except Exception:
        logger.exception("Poll cycle failed unexpectedly")
