"""Auto-generate post-incident reports when a service recovers.

Triggered by change_detector when a service transitions back to operational.
Uses a 5-minute cooldown to handle flapping services.
"""

import json
import logging
from datetime import datetime, timezone

import aiosqlite

from app.dependencies.graph import get_downstream

logger = logging.getLogger(__name__)

SEVERITY_RANK = {
    "major_outage": 4,
    "partial_outage": 3,
    "degraded": 2,
    "operational": 1,
    "unknown": 0,
}


async def generate_incident_report(
    db: aiosqlite.Connection,
    write_lock: "asyncio.Lock",
    service_id: str,
    resolved_at: str,
) -> dict | None:
    """Generate a post-incident report for a service that just recovered.

    Walks backwards from resolved_at to find the incident start, collects
    all events during the window, computes metrics, and stores the report.
    """
    import asyncio

    # Verify service is still operational (cooldown check)
    cursor = await db.execute(
        "SELECT current_status, display_name FROM services WHERE id = ?",
        (service_id,),
    )
    row = await cursor.fetchone()
    if not row or row[0] != "operational":
        logger.debug("Service %s no longer operational, skipping report", service_id)
        return None

    service_name = row[1]

    # Find the incident window: walk backwards to find when it started
    cursor = await db.execute(
        """SELECT id, previous_status, new_status, vendor_title, vendor_detail,
                  impact_statement, source, created_at
           FROM status_events
           WHERE service_id = ?
           ORDER BY created_at DESC""",
        (service_id,),
    )
    all_events = [dict(r) for r in await cursor.fetchall()]

    if not all_events:
        return None

    # Find the recovery event and the incident start
    incident_events = []
    found_recovery = False

    for event in all_events:
        if not found_recovery:
            if event["new_status"] == "operational" and event["previous_status"] != "unknown":
                found_recovery = True
                incident_events.append(event)
            continue

        # We're walking backwards through the incident
        incident_events.append(event)

        # Stop when we find the event that started the incident
        # (the one where previous_status was operational)
        if event["previous_status"] == "operational":
            break

    if len(incident_events) < 2:
        return None  # No real incident to report

    incident_events.reverse()  # Chronological order
    started_at = incident_events[0]["created_at"]

    # Compute metrics
    try:
        start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))
        duration_seconds = int((end_dt - start_dt).total_seconds())
    except (ValueError, TypeError):
        duration_seconds = 0

    if duration_seconds < 60:
        return None  # Too brief to report

    # Peak severity
    peak = max(incident_events, key=lambda e: SEVERITY_RANK.get(e["new_status"], 0))
    peak_severity = peak["new_status"]

    # Downstream affected services
    downstream = await get_downstream(db, service_id)
    affected_names = [d["service_name"] for d in downstream]

    # Generate summary
    duration_human = _format_duration(duration_seconds)
    impact_summary = (
        f"{service_name} experienced {peak_severity.replace('_', ' ')} "
        f"for {duration_human}. "
    )
    if affected_names:
        impact_summary += f"Potentially affected: {', '.join(affected_names[:5])}."
        if len(affected_names) > 5:
            impact_summary += f" (+{len(affected_names) - 5} more)"

    # Store report
    async with write_lock:
        await db.execute(
            """INSERT INTO incident_reports
               (service_id, started_at, resolved_at, duration_seconds,
                peak_severity, affected_downstream, event_count,
                events_json, impact_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                service_id, started_at, resolved_at, duration_seconds,
                peak_severity, json.dumps(affected_names),
                len(incident_events), json.dumps(incident_events),
                impact_summary,
            ),
        )
        await db.commit()

    logger.info(
        "Generated incident report for %s: %s, duration %s, peak %s",
        service_name, started_at, duration_human, peak_severity,
    )

    return {
        "service_id": service_id,
        "service_name": service_name,
        "started_at": started_at,
        "resolved_at": resolved_at,
        "duration_seconds": duration_seconds,
        "duration_human": duration_human,
        "peak_severity": peak_severity,
        "affected_downstream": affected_names,
        "event_count": len(incident_events),
        "impact_summary": impact_summary,
    }


def _format_duration(seconds: int) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    remaining_min = minutes % 60
    if remaining_min:
        return f"{hours}h {remaining_min}m"
    return f"{hours}h"
