"""Summary and maintenance API routes."""

from fastapi import APIRouter

from app.alerting.templates import generate_summary_text
from app.database import get_db
from app.dependencies.graph import get_downstream

router = APIRouter(prefix="/api", tags=["summary"])


@router.get("/summary")
async def get_summary() -> dict:
    """Overall health summary with active incidents and upcoming maintenances."""
    db = await get_db()

    # Service counts
    cursor = await db.execute(
        """SELECT current_status, count(*) as cnt
           FROM services GROUP BY current_status"""
    )
    counts = {row[0]: row[1] for row in await cursor.fetchall()}

    total = sum(counts.values())
    healthy = counts.get("operational", 0)
    degraded = counts.get("degraded", 0)
    partial = counts.get("partial_outage", 0)
    major = counts.get("major_outage", 0)
    unknown = counts.get("unknown", 0)
    outage = partial + major

    # Compute overall status (worst non-unknown)
    if major > 0:
        overall = "major_outage"
    elif partial > 0:
        overall = "partial_outage"
    elif degraded > 0:
        overall = "degraded"
    else:
        overall = "operational"

    # Active incidents (services not operational or unknown)
    cursor = await db.execute(
        """SELECT s.id, s.display_name, s.category, s.current_status,
                  s.current_status_detail, s.poll_type, s.status_page_url,
                  s.last_polled_at, s.last_status_change_at
           FROM services s
           WHERE s.current_status NOT IN ('operational', 'unknown')
           ORDER BY
               CASE s.current_status
                   WHEN 'major_outage' THEN 1
                   WHEN 'partial_outage' THEN 2
                   WHEN 'degraded' THEN 3
               END,
               s.last_status_change_at DESC"""
    )
    incident_rows = [dict(r) for r in await cursor.fetchall()]

    active_incidents = []
    incident_names = []
    for svc in incident_rows:
        # Get most recent impact statement
        cursor = await db.execute(
            """SELECT impact_statement FROM status_events
               WHERE service_id = ? ORDER BY created_at DESC LIMIT 1""",
            (svc["id"],),
        )
        event_row = await cursor.fetchone()
        impact = dict(event_row)["impact_statement"] if event_row else ""

        # Get downstream affected services
        downstream = await get_downstream(db, svc["id"])
        affected = [d["service_name"] for d in downstream]

        active_incidents.append({
            "service": svc,
            "impact_statement": impact or f"{svc['display_name']} status: {svc['current_status']}",
            "affected_services": affected,
            "started_at": svc["last_status_change_at"],
        })
        incident_names.append(svc["display_name"])

    # Status text
    status_text = generate_summary_text(total, len(incident_rows), incident_names)

    # Upcoming maintenances
    cursor = await db.execute(
        """SELECT sm.id, sm.service_id, s.display_name as service_name,
                  sm.title, sm.description, sm.scheduled_for, sm.scheduled_until, sm.status
           FROM scheduled_maintenances sm
           JOIN services s ON s.id = sm.service_id
           WHERE sm.status IN ('scheduled', 'in_progress', 'verifying')
           ORDER BY sm.scheduled_for ASC"""
    )
    maintenances = [dict(r) for r in await cursor.fetchall()]

    # Last poll
    cursor = await db.execute(
        "SELECT MAX(last_polled_at) FROM services WHERE last_polled_at IS NOT NULL"
    )
    row = await cursor.fetchone()
    last_poll = row[0] if row else None

    return {
        "data": {
            "overall_status": overall,
            "status_text": status_text,
            "active_incidents": active_incidents,
            "upcoming_maintenances": maintenances,
            "total_services": total,
            "healthy_count": healthy,
            "degraded_count": degraded,
            "outage_count": outage,
            "unknown_count": unknown,
            "last_poll_at": last_poll,
        },
        "error": None,
        "meta": None,
    }


@router.get("/maintenance")
async def get_maintenance() -> dict:
    """Get upcoming and active scheduled maintenances."""
    db = await get_db()

    cursor = await db.execute(
        """SELECT sm.id, sm.service_id, s.display_name as service_name,
                  sm.title, sm.description, sm.scheduled_for, sm.scheduled_until, sm.status
           FROM scheduled_maintenances sm
           JOIN services s ON s.id = sm.service_id
           WHERE sm.status IN ('scheduled', 'in_progress', 'verifying')
           ORDER BY sm.scheduled_for ASC"""
    )
    maintenances = [dict(r) for r in await cursor.fetchall()]

    return {
        "data": {"maintenances": maintenances, "total": len(maintenances)},
        "error": None,
        "meta": None,
    }
