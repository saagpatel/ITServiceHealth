"""Data retention — keep append-only tables from growing forever.

Two append-only tables gather rows indefinitely under normal operation:

- `status_events`  — every confirmed status transition
- `alert_sent_log` — every fire/suppression decision

On a running dashboard these both grow linearly with time. Without
retention a deployment left alone for 6 months has a 10x larger DB
and correspondingly slower range queries on the timeline view.

The retention job runs once a week (configurable via
`RETENTION_INTERVAL_HOURS`) and deletes rows older than the
per-table `retention_days_*` setting. A subsequent WAL checkpoint
is required to actually reclaim disk space; retention itself only
removes rows from the logical table.

The WAL-checkpoint job runs daily and is independent — even without
retention, a long-lived WAL file should be truncated periodically
so the -wal sidecar doesn't grow without bound.

Both jobs are safe to run concurrently with polls because aiosqlite
serializes writes, and DELETE statements hold only brief locks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiosqlite

from app.database import checkpoint_wal, get_db, get_write_lock

logger = logging.getLogger(__name__)


@dataclass
class RetentionResult:
    status_events_deleted: int
    alert_sent_log_deleted: int
    checkpoint_pages_reclaimed: int


async def purge_old_rows(
    db: aiosqlite.Connection | None = None,
    status_events_days: int = 90,
    alert_sent_log_days: int = 90,
    checkpoint_after: bool = True,
) -> RetentionResult:
    """Delete rows older than the per-table retention windows.

    `status_events_days=0` or `alert_sent_log_days=0` disables retention
    for that table (useful in tests and for operators who want infinite
    history).

    Runs under the write lock to avoid contention with the poll cycle.
    """
    target = db or await get_db()
    write_lock = get_write_lock()

    events_deleted = 0
    alerts_deleted = 0
    pages_reclaimed = 0

    async with write_lock:
        if status_events_days > 0:
            cursor = await target.execute(
                "DELETE FROM status_events WHERE created_at < datetime('now', ? || ' days')",
                (f"-{status_events_days}",),
            )
            events_deleted = cursor.rowcount or 0

        if alert_sent_log_days > 0:
            cursor = await target.execute(
                "DELETE FROM alert_sent_log WHERE first_sent_at < datetime('now', ? || ' days')",
                (f"-{alert_sent_log_days}",),
            )
            alerts_deleted = cursor.rowcount or 0

        await target.commit()

    if checkpoint_after:
        _, _, pages_reclaimed = await checkpoint_wal(target)

    logger.info(
        "Retention: %d status_events deleted, %d alert_sent_log deleted, "
        "%d WAL pages reclaimed",
        events_deleted, alerts_deleted, pages_reclaimed,
    )

    return RetentionResult(
        status_events_deleted=events_deleted,
        alert_sent_log_deleted=alerts_deleted,
        checkpoint_pages_reclaimed=pages_reclaimed,
    )


async def scheduled_retention_tick() -> None:
    """APScheduler entry point — reads config, runs retention, logs result.

    Wraps purge_old_rows with the currently configured windows. Failures
    are caught + logged so one bad week of retention can't take down
    the scheduler.
    """
    from app.config import settings
    try:
        await purge_old_rows(
            status_events_days=settings.retention_days_status_events,
            alert_sent_log_days=settings.retention_days_alert_sent_log,
            checkpoint_after=True,
        )
    except Exception:
        logger.exception("Retention tick failed")


async def scheduled_wal_checkpoint_tick() -> None:
    """APScheduler entry point for the daily WAL checkpoint.

    Independent from retention — a long-lived WAL file should be
    truncated regularly even when no DELETE statements run.
    """
    try:
        await checkpoint_wal()
    except Exception:
        logger.exception("WAL checkpoint tick failed")
