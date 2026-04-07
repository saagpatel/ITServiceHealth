"""Service API routes: list all services, get service detail with dependencies."""

from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.dependencies.graph import get_downstream, get_upstream

router = APIRouter(prefix="/api", tags=["services"])


@router.get("/services")
async def list_services(category: str | None = None) -> dict:
    """List all services with current status and aggregate counts."""
    db = await get_db()

    if category:
        cursor = await db.execute(
            """SELECT id, display_name, category, current_status, current_status_detail,
                      poll_type, status_page_url, last_polled_at, last_status_change_at
               FROM services WHERE category = ? ORDER BY category, display_name""",
            (category,),
        )
    else:
        cursor = await db.execute(
            """SELECT id, display_name, category, current_status, current_status_detail,
                      poll_type, status_page_url, last_polled_at, last_status_change_at
               FROM services ORDER BY category, display_name"""
        )

    rows = [dict(r) for r in await cursor.fetchall()]

    healthy = sum(1 for r in rows if r["current_status"] == "operational")
    degraded = sum(1 for r in rows if r["current_status"] == "degraded")
    outage = sum(1 for r in rows if r["current_status"] in ("partial_outage", "major_outage"))
    unknown = sum(1 for r in rows if r["current_status"] == "unknown")

    return {
        "data": {
            "services": rows,
            "total": len(rows),
            "healthy_count": healthy,
            "degraded_count": degraded,
            "outage_count": outage,
            "unknown_count": unknown,
        },
        "error": None,
        "meta": {"category_filter": category},
    }


@router.get("/services/{service_id}")
async def get_service_detail(service_id: str) -> dict:
    """Get a single service with dependencies and recent events."""
    db = await get_db()

    cursor = await db.execute(
        """SELECT id, display_name, category, current_status, current_status_detail,
                  poll_type, status_page_url, last_polled_at, last_status_change_at
           FROM services WHERE id = ?""",
        (service_id,),
    )
    svc = await cursor.fetchone()
    if not svc:
        raise HTTPException(
            status_code=404,
            detail={
                "data": None,
                "error": {
                    "code": "SERVICE_NOT_FOUND",
                    "message": f"Service '{service_id}' not found",
                },
                "meta": None,
            },
        )

    downstream = await get_downstream(db, service_id)
    upstream = await get_upstream(db, service_id)

    cursor = await db.execute(
        """SELECT se.id, se.service_id, s.display_name as service_name,
                  se.previous_status, se.new_status, se.vendor_title, se.vendor_detail,
                  se.impact_statement, se.source, se.created_at
           FROM status_events se
           JOIN services s ON s.id = se.service_id
           WHERE se.service_id = ?
           ORDER BY se.created_at DESC LIMIT 10""",
        (service_id,),
    )
    events = [dict(r) for r in await cursor.fetchall()]

    return {
        "data": {
            "service": dict(svc),
            "downstream_impacts": downstream,
            "upstream_dependencies": upstream,
            "recent_events": events,
        },
        "error": None,
        "meta": None,
    }
