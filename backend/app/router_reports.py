"""Incident reports API: auto-generated post-incident summaries."""

import json

from fastapi import APIRouter

from app.database import get_db
from app.reports import _format_duration

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/reports")
async def get_reports(service_id: str | None = None, limit: int = 20) -> dict:
    """Get incident reports, optionally filtered by service."""
    db = await get_db()
    limit = max(1, min(limit, 100))

    if service_id:
        cursor = await db.execute(
            """SELECT ir.id, ir.service_id, s.display_name as service_name,
                      ir.started_at, ir.resolved_at, ir.duration_seconds,
                      ir.peak_severity, ir.affected_downstream,
                      ir.event_count, ir.impact_summary, ir.created_at
               FROM incident_reports ir
               JOIN services s ON s.id = ir.service_id
               WHERE ir.service_id = ?
               ORDER BY ir.created_at DESC LIMIT ?""",
            (service_id, limit),
        )
    else:
        cursor = await db.execute(
            """SELECT ir.id, ir.service_id, s.display_name as service_name,
                      ir.started_at, ir.resolved_at, ir.duration_seconds,
                      ir.peak_severity, ir.affected_downstream,
                      ir.event_count, ir.impact_summary, ir.created_at
               FROM incident_reports ir
               JOIN services s ON s.id = ir.service_id
               ORDER BY ir.created_at DESC LIMIT ?""",
            (limit,),
        )

    rows = await cursor.fetchall()
    reports = []
    for row in rows:
        r = dict(row)
        r["duration_human"] = _format_duration(r["duration_seconds"])
        r["affected_downstream"] = json.loads(r["affected_downstream"]) if r["affected_downstream"] else []
        reports.append(r)

    return {
        "data": {"reports": reports, "total": len(reports)},
        "error": None,
        "meta": {"service_id_filter": service_id},
    }
