"""Change detector: diffs poll results against DB state and writes changes.

Handles status change detection, status_events creation, service updates,
and scheduled maintenance upserts. Used by both the automated poll cycle
and the manual status update API.

Also tracks per-service poller health (healthy | degraded | broken) so
the UI can distinguish "vendor is down" from "our poller is blind." A run
of consecutive failures past the configured threshold flips the service
to `broken`; a single success clears it.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite

from app.config import settings
from app.poller.normalizer import ServiceStatus
from app.poller.statuspage_poller import PollResult

logger = logging.getLogger(__name__)


@dataclass
class StatusChange:
    """A detected status change, carrying everything Phase 1B alerting needs."""

    service_id: str
    service_display_name: str
    previous_status: str
    new_status: str
    status_detail: str | None
    poll_type: str
    status_page_url: str | None
    event_id: int | None = None


@dataclass
class PollerHealthChange:
    """Poller-health state transition detected during a poll cycle.

    Emitted alongside StatusChange for the alerting engine to route onto a
    distinct Slack channel: vendor outages are one kind of news, our own
    blind spot is another. Only the transitions in/out of `broken` produce
    these; the noisy `healthy -> degraded` path stays silent by design.
    """

    service_id: str
    service_display_name: str
    previous_health: str
    new_health: str
    consecutive_failures: int
    failure_reason: str | None


def _compute_new_health(
    current_health: str,
    consecutive_failures: int,
    poll_succeeded: bool,
    threshold: int,
) -> str:
    """Pure state-machine decision for the new poller_health value.

    - A successful poll always resets to 'healthy'.
    - After `threshold` consecutive failures, health is 'broken'.
    - Any failure short of the threshold is 'degraded'.
    """
    if poll_succeeded:
        return "healthy"
    if consecutive_failures >= threshold:
        return "broken"
    return "degraded"


async def detect_changes(
    db: aiosqlite.Connection,
    write_lock: "asyncio.Lock",
    poll_results: list[tuple[str, PollResult]],
) -> tuple[list[StatusChange], list[PollerHealthChange]]:
    """Compare poll results against current DB state and write changes.

    Returns a pair (status_changes, health_changes) so the caller can route
    vendor-outage alerts and poller-health alerts onto distinct Slack
    channels with different urgency policies.

    For each poll result:
    - Poller health is always reassessed (success clears, failures
      accumulate, threshold crossings emit PollerHealthChange).
    - If UNKNOWN: preserve current status, update last_polled_at + health.
    - If status changed: update service + insert status_event.
    - If same status: update last_polled_at and current_status_detail.

    Also upserts scheduled maintenances from statuspage poll results.
    """
    import asyncio

    if not poll_results:
        return [], []

    service_ids = [sid for sid, _ in poll_results]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Batch-read current state including poller-health trail
    placeholders = ",".join("?" for _ in service_ids)
    cursor = await db.execute(
        f"""SELECT id, display_name, current_status, poll_type, status_page_url,
                   consecutive_failures, poller_health
            FROM services WHERE id IN ({placeholders})""",
        service_ids,
    )
    rows = await cursor.fetchall()
    current_state = {row[0]: dict(row) for row in rows}

    changes: list[StatusChange] = []
    health_changes: list[PollerHealthChange] = []
    threshold = settings.poller_failure_threshold

    async with write_lock:
        for service_id, poll_result in poll_results:
            svc = current_state.get(service_id)
            if not svc:
                logger.warning("Service '%s' not found in DB, skipping", service_id)
                continue

            poll_succeeded = poll_result.status != ServiceStatus.UNKNOWN
            prev_health = svc["poller_health"]
            prev_failures = svc["consecutive_failures"] or 0

            new_failures = 0 if poll_succeeded else prev_failures + 1
            new_health = _compute_new_health(
                prev_health, new_failures, poll_succeeded, threshold,
            )

            # Only emit health changes for broken transitions — the signal
            # we want operators to see in #poller-health.
            if prev_health != "broken" and new_health == "broken":
                health_changes.append(PollerHealthChange(
                    service_id=service_id,
                    service_display_name=svc["display_name"],
                    previous_health=prev_health,
                    new_health=new_health,
                    consecutive_failures=new_failures,
                    failure_reason=poll_result.poll_failure_reason,
                ))
                logger.warning(
                    "Poller BROKEN for %s (%s) after %d failures: %s",
                    svc["display_name"], service_id,
                    new_failures, poll_result.poll_failure_reason,
                )
            elif prev_health == "broken" and new_health == "healthy":
                health_changes.append(PollerHealthChange(
                    service_id=service_id,
                    service_display_name=svc["display_name"],
                    previous_health=prev_health,
                    new_health=new_health,
                    consecutive_failures=0,
                    failure_reason=None,
                ))
                logger.info(
                    "Poller RECOVERED for %s (%s)",
                    svc["display_name"], service_id,
                )

            # Update the health-trail columns every cycle
            await db.execute(
                """UPDATE services
                   SET consecutive_failures = ?,
                       poller_health = ?,
                       last_failure_reason = ?,
                       last_success_at = CASE WHEN ? THEN ? ELSE last_success_at END,
                       last_polled_at = ?
                   WHERE id = ?""",
                (
                    new_failures,
                    new_health,
                    poll_result.poll_failure_reason if not poll_succeeded else None,
                    poll_succeeded, now,
                    now,
                    service_id,
                ),
            )

            # If poll failed, preserve last-known status and move on
            if not poll_succeeded:
                continue

            new_status = poll_result.status.value
            old_status = svc["current_status"]

            if new_status != old_status:
                # Status changed — update service and create event
                await db.execute(
                    """UPDATE services
                       SET current_status = ?, current_status_detail = ?,
                           last_status_change_at = ?
                       WHERE id = ?""",
                    (new_status, poll_result.status_detail, now, service_id),
                )

                vendor_title = _extract_vendor_title(poll_result)
                cursor_ins = await db.execute(
                    """INSERT INTO status_events
                       (service_id, previous_status, new_status, vendor_title,
                        vendor_detail, source, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        service_id, old_status, new_status, vendor_title,
                        poll_result.status_detail, svc["poll_type"], now,
                    ),
                )
                event_id = cursor_ins.lastrowid

                changes.append(StatusChange(
                    service_id=service_id,
                    service_display_name=svc["display_name"],
                    previous_status=old_status,
                    new_status=new_status,
                    status_detail=poll_result.status_detail,
                    poll_type=svc["poll_type"],
                    status_page_url=svc["status_page_url"],
                    event_id=event_id,
                ))

                logger.info(
                    "Status change: %s (%s) %s → %s",
                    svc["display_name"], service_id, old_status, new_status,
                )
            else:
                # Same status — just update detail
                await db.execute(
                    """UPDATE services
                       SET current_status_detail = ?
                       WHERE id = ?""",
                    (poll_result.status_detail, service_id),
                )

            # Upsert scheduled maintenances (statuspage services only)
            if poll_result.scheduled_maintenances:
                await upsert_maintenances(db, service_id, poll_result.scheduled_maintenances)

        await db.commit()

    return changes, health_changes


async def apply_manual_update(
    db: aiosqlite.Connection,
    write_lock: "asyncio.Lock",
    service_id: str,
    new_status: ServiceStatus,
    detail: str | None,
    updated_by: str | None = None,
    reason: str | None = None,
    client_ip: str | None = None,
) -> StatusChange | None:
    """Apply a manual status update through the same change detection path.

    Audit fields (updated_by, reason, client_ip) are written to status_events
    on status change. The admin API always supplies them; other callers may
    omit them.

    Returns StatusChange if status actually changed, None if same status.
    """
    import asyncio

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cursor = await db.execute(
        "SELECT id, display_name, current_status, poll_type, status_page_url FROM services WHERE id = ?",
        (service_id,),
    )
    svc = await cursor.fetchone()
    if not svc:
        raise ValueError(f"Service '{service_id}' not found")

    svc = dict(svc)
    old_status = svc["current_status"]

    async with write_lock:
        if new_status.value != old_status:
            await db.execute(
                """UPDATE services
                   SET current_status = ?, current_status_detail = ?,
                       last_status_change_at = ?
                   WHERE id = ?""",
                (new_status.value, detail, now, service_id),
            )
            cursor_ins = await db.execute(
                """INSERT INTO status_events
                   (service_id, previous_status, new_status, vendor_title,
                    vendor_detail, source, created_at,
                    updated_by, reason, client_ip)
                   VALUES (?, ?, ?, ?, ?, 'manual', ?, ?, ?, ?)""",
                (
                    service_id, old_status, new_status.value, None, detail, now,
                    updated_by, reason, client_ip,
                ),
            )
            event_id = cursor_ins.lastrowid
            await db.commit()

            return StatusChange(
                service_id=service_id,
                service_display_name=svc["display_name"],
                previous_status=old_status,
                new_status=new_status.value,
                status_detail=detail,
                poll_type="manual",
                status_page_url=svc["status_page_url"],
                event_id=event_id,
            )
        else:
            # Same status — update detail only if provided
            if detail is not None:
                await db.execute(
                    "UPDATE services SET current_status_detail = ? WHERE id = ?",
                    (detail, service_id),
                )
                await db.commit()
            return None


async def upsert_maintenances(
    db: aiosqlite.Connection,
    service_id: str,
    maintenances: list[dict],
) -> None:
    """Upsert scheduled maintenances from a Statuspage.io response.

    Deduplicates by (service_id, vendor_maintenance_id) using the partial
    unique index from migration 0002.
    """
    for m in maintenances:
        vendor_id = m.get("id")
        if not vendor_id:
            continue

        title = m.get("name", "Scheduled Maintenance")
        updates = m.get("incident_updates", [])
        description = updates[0].get("body") if updates else None
        scheduled_for = m.get("scheduled_for")
        scheduled_until = m.get("scheduled_until")
        status = m.get("status", "scheduled")

        if not scheduled_for:
            continue

        # Check if this maintenance already exists
        cursor = await db.execute(
            """SELECT id FROM scheduled_maintenances
               WHERE service_id = ? AND vendor_maintenance_id = ?""",
            (service_id, str(vendor_id)),
        )
        existing = await cursor.fetchone()

        if existing:
            await db.execute(
                """UPDATE scheduled_maintenances
                   SET title = ?, description = ?, scheduled_for = ?,
                       scheduled_until = ?, status = ?
                   WHERE service_id = ? AND vendor_maintenance_id = ?""",
                (title, description, scheduled_for, scheduled_until,
                 status, service_id, str(vendor_id)),
            )
        else:
            await db.execute(
                """INSERT INTO scheduled_maintenances
                   (service_id, vendor_maintenance_id, title, description,
                    scheduled_for, scheduled_until, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (service_id, str(vendor_id), title, description,
                 scheduled_for, scheduled_until, status),
            )


def _extract_vendor_title(poll_result: PollResult) -> str | None:
    """Extract a vendor incident title from poll result."""
    if poll_result.incidents:
        first = poll_result.incidents[0]
        return first.get("name") or first.get("title")
    return None
