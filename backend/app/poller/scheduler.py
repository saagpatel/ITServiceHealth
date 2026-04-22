"""Poll scheduler: runs all pollers on a 60-second cycle via APScheduler.

Orchestrates statuspage, Slack, and Google pollers, feeds results through
the change detector, and logs status changes.

Phase 3 observability hooks:
  - Each poll cycle binds a fresh `poll_cycle_id` contextvar so every
    log line emitted during the cycle carries it (trace-without-tracing).
  - `poll_cycles_total{outcome}` counter increments on every cycle.
  - A separate heartbeat job pings Healthchecks.io + updates the
    `scheduler_last_heartbeat_seconds` gauge.
  - APScheduler event listeners log EVENT_JOB_ERROR / EVENT_JOB_MISSED so
    a silently-dead scheduler becomes visible in metrics + logs.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import structlog
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import get_db, get_write_lock
from app.observability.heartbeat import heartbeat_tick, update_heartbeat_gauge_continuously
from app.observability.metrics import POLL_CYCLES_TOTAL, POLL_DURATION_SECONDS

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(
    timezone=ZoneInfo("UTC"),
    job_defaults={
        # Coalesce drops all-but-one pending run when we wake up late
        # after a hang, instead of replaying a thundering herd.
        "coalesce": True,
        # Never let two poll cycles overlap — a slow cycle gets skipped
        # rather than racing with the next one.
        "max_instances": 1,
        # If the scheduler wakes up within 30s late we still run; more
        # than 30s late = skip this tick and log it via EVENT_JOB_MISSED.
        "misfire_grace_time": 30,
    },
)


def _on_scheduler_event(event) -> None:
    """Bridge APScheduler events into our logs + metrics."""
    if event.code == EVENT_JOB_ERROR:
        logger.error(
            "APScheduler job %s raised: %s", event.job_id, event.exception,
        )
    elif event.code == EVENT_JOB_MISSED:
        logger.warning(
            "APScheduler job %s missed its run time at %s",
            event.job_id, event.scheduled_run_time,
        )


def start_scheduler(app) -> None:
    """Start the poll scheduler with immediate first run."""
    scheduler.add_listener(_on_scheduler_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)

    # Poll cycle — the main event
    scheduler.add_job(
        run_poll_cycle,
        "interval",
        seconds=settings.poll_interval_seconds,
        args=[app],
        id="poll_cycle",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
    )

    # Heartbeat — proves we're alive even when no poll is happening
    scheduler.add_job(
        heartbeat_tick,
        "interval",
        seconds=settings.heartbeat_interval_seconds,
        id="heartbeat",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
    )

    # Gauge refresher — keeps scheduler_last_heartbeat_seconds accurate for
    # scrapers between heartbeat ticks.
    scheduler.add_job(
        update_heartbeat_gauge_continuously,
        "interval",
        seconds=5,
        id="heartbeat_gauge",
        replace_existing=True,
    )

    # WAL checkpoint — runs more often than retention so the -wal sidecar
    # file doesn't grow without bound between weekly retention passes.
    from app.retention import scheduled_retention_tick, scheduled_wal_checkpoint_tick
    scheduler.add_job(
        scheduled_wal_checkpoint_tick,
        "interval",
        hours=settings.wal_checkpoint_interval_hours,
        id="wal_checkpoint",
        replace_existing=True,
    )

    # Retention — weekly by default, purges rows older than the configured
    # per-table windows and runs a truncating checkpoint to reclaim disk.
    scheduler.add_job(
        scheduled_retention_tick,
        "interval",
        hours=settings.retention_interval_hours,
        id="retention",
        replace_existing=True,
    )

    # Daily SQLite VACUUM INTO backup — independent of Litestream, kept
    # as a belt-and-suspenders snapshot for operators who don't want to
    # set up Litestream's continuous WAL shipping.
    from app.backup import run_backup
    scheduler.add_job(
        run_backup,
        "cron",
        hour=settings.backup_time_hour,
        minute=0,
        id="daily_backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info(
        "Poll scheduler started (poll=%ds, heartbeat=%ds, checkpoint=%dh, "
        "retention=%dh, backup=%02d:00 UTC)",
        settings.poll_interval_seconds,
        settings.heartbeat_interval_seconds,
        settings.wal_checkpoint_interval_hours,
        settings.retention_interval_hours,
        settings.backup_time_hour,
    )


def stop_scheduler() -> None:
    """Stop the poll scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Poll scheduler stopped")


async def run_poll_cycle(app) -> None:
    """Execute one full poll cycle across all automated services.

    Binds `poll_cycle_id` so every log line emitted during the cycle
    (including from deep inside pollers / change detector / alerting)
    carries it. Operators grep the JSON log by poll_cycle_id to see
    every downstream effect of a single tick.
    """
    cycle_id = uuid.uuid4().hex[:12]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(poll_cycle_id=cycle_id)

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
        from app.poller.google_poller import poll_google
        from app.poller.ringcentral_poller import poll_ringcentral
        from app.poller.salesforce_poller import poll_salesforce
        from app.poller.slack_poller import poll_slack
        from app.poller.statuspage_poller import poll_all_statuspage
        from app.poller.zendesk_poller import poll_zendesk

        tasks = []
        task_labels = []

        def _timed(poll_type: str, coro):
            """Wrap a poller coroutine to record its wall-clock duration."""
            async def _runner():
                with POLL_DURATION_SECONDS.labels(poll_type=poll_type).time():
                    return await coro
            return _runner()

        statuspage_svcs = services_by_type.get("statuspage_json", [])
        if statuspage_svcs:
            tasks.append(_timed("statuspage_json", poll_all_statuspage(client, statuspage_svcs)))
            task_labels.append(f"statuspage ({len(statuspage_svcs)} services)")

        slack_svcs = services_by_type.get("slack_api", [])
        if slack_svcs:
            svc = slack_svcs[0]

            async def _poll_slack():
                result = await poll_slack(client, svc["poll_url"])
                return [(svc["id"], result)]

            tasks.append(_timed("slack_api", _poll_slack()))
            task_labels.append("slack (1 service)")

        google_svcs = services_by_type.get("google_json", [])
        if google_svcs:
            url = google_svcs[0]["poll_url"]
            tasks.append(_timed("google_json", poll_google(client, url, google_svcs)))
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
                tasks.append(_timed(poll_type, _poll_single()))
                task_labels.append(f"{poll_type} ({svc['id']})")

        if not tasks:
            logger.warning("No pollable services found")
            POLL_CYCLES_TOTAL.labels(outcome="completed").inc()
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

        changes, health_changes = await detect_changes(db, write_lock, all_results)

        # Process vendor-outage changes: impact statements + Slack alerts
        if changes:
            from app.alerting.engine import process_changes
            await process_changes(db, write_lock, changes, http_client=client)

        # Process poller-health changes: alert on the separate poller-health
        # webhook so operators can tell "we're blind" from "vendor is down".
        if health_changes:
            from app.alerting.engine import process_poller_health_changes
            await process_poller_health_changes(
                health_changes, http_client=client,
            )

        # Log summary
        logger.info(
            "Poll cycle complete: %d services polled, %d changes, %d health",
            len(all_results), len(changes), len(health_changes),
        )
        for change in changes:
            logger.info(
                "  %s: %s → %s",
                change.service_display_name,
                change.previous_status,
                change.new_status,
            )
        for hc in health_changes:
            logger.info(
                "  [health] %s: %s → %s (%d fails)",
                hc.service_display_name,
                hc.previous_health,
                hc.new_health,
                hc.consecutive_failures,
            )
        POLL_CYCLES_TOTAL.labels(outcome="completed").inc()

    except Exception:
        POLL_CYCLES_TOTAL.labels(outcome="errored").inc()
        logger.exception("Poll cycle failed unexpectedly")
    finally:
        structlog.contextvars.clear_contextvars()
