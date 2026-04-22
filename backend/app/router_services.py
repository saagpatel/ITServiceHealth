"""Service API routes: list all services, get service detail with dependencies."""

from datetime import UTC, datetime, timedelta

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
                      poll_type, status_page_url, last_polled_at, last_status_change_at,
                      consecutive_failures, last_success_at, last_failure_reason, poller_health,
                      tier
               FROM services WHERE category = ? ORDER BY category, display_name""",
            (category,),
        )
    else:
        cursor = await db.execute(
            """SELECT id, display_name, category, current_status, current_status_detail,
                      poll_type, status_page_url, last_polled_at, last_status_change_at,
                      consecutive_failures, last_success_at, last_failure_reason, poller_health,
                      tier
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


@router.get("/services/uptime")
async def get_services_uptime() -> dict:
    """Get per-service, per-day worst status over the past 7 days."""
    db = await get_db()

    # Generate the last 7 days
    now = datetime.now(UTC)
    days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

    cursor = await db.execute(
        """SELECT service_id,
                  DATE(created_at) as day,
                  CASE MAX(CASE new_status
                      WHEN 'major_outage' THEN 4
                      WHEN 'partial_outage' THEN 3
                      WHEN 'degraded' THEN 2
                      ELSE 1 END)
                  WHEN 4 THEN 'major_outage'
                  WHEN 3 THEN 'partial_outage'
                  WHEN 2 THEN 'degraded'
                  ELSE 'operational' END as worst_status
           FROM status_events
           WHERE created_at >= datetime('now', '-7 days')
             AND NOT (previous_status = 'unknown' AND new_status = 'operational')
           GROUP BY service_id, DATE(created_at)"""
    )
    rows = await cursor.fetchall()

    services: dict[str, dict[str, str]] = {}
    for row in rows:
        sid = row[0]
        if sid not in services:
            services[sid] = {}
        services[sid][row[1]] = row[2]

    return {
        "data": {"days": days, "services": services},
        "error": None,
        "meta": None,
    }


@router.get("/services/sla")
async def get_services_sla() -> dict:
    """Get per-service uptime percentages for 24h, 7d, and 30d windows."""
    db = await get_db()

    results: dict[str, dict[str, float | None]] = {}

    for window_label, window_days in [("uptime_24h", 1), ("uptime_7d", 7), ("uptime_30d", 30)]:
        cursor = await db.execute(
            """WITH intervals AS (
                SELECT service_id, new_status as status,
                       created_at as started,
                       LEAD(created_at) OVER (PARTITION BY service_id ORDER BY created_at) as ended
                FROM status_events
                WHERE created_at >= datetime('now', ? || ' days')
                  AND NOT (previous_status = 'unknown' AND new_status = 'operational')
               )
               SELECT service_id,
                      SUM(CASE WHEN status = 'operational'
                          THEN (julianday(COALESCE(ended, datetime('now'))) - julianday(started)) * 86400
                          ELSE 0 END) as operational_seconds,
                      SUM(CASE WHEN status != 'unknown'
                          THEN (julianday(COALESCE(ended, datetime('now'))) - julianday(started)) * 86400
                          ELSE 0 END) as tracked_seconds
               FROM intervals
               WHERE status != 'unknown'
               GROUP BY service_id""",
            (f"-{window_days}",),
        )
        rows = await cursor.fetchall()

        for row in rows:
            sid = row[0]
            operational = row[1] or 0
            tracked = row[2] or 0

            if sid not in results:
                results[sid] = {"uptime_24h": None, "uptime_7d": None, "uptime_30d": None}

            if tracked > 0:
                pct = round((operational / tracked) * 100, 2)
                results[sid][window_label] = min(pct, 100.0)

    return {
        "data": {"services": results},
        "error": None,
        "meta": None,
    }


@router.get("/services/graph")
async def get_service_graph() -> dict:
    """Get service dependency graph in node/link format for visualization."""
    db = await get_db()

    # Nodes: all services with current status and downstream count
    cursor = await db.execute(
        """SELECT s.id, s.display_name, s.category, s.current_status,
                  (SELECT COUNT(*) FROM service_dependencies WHERE upstream_service_id = s.id) as downstream_count
           FROM services s ORDER BY s.display_name"""
    )
    nodes = [
        {
            "id": row[0],
            "name": row[1],
            "category": row[2],
            "status": row[3],
            "downstream_count": row[4],
        }
        for row in await cursor.fetchall()
    ]

    # Links: all dependencies
    cursor = await db.execute(
        """SELECT sd.upstream_service_id as source,
                  sd.downstream_service_id as target,
                  sd.severity,
                  sd.impact_description as impact
           FROM service_dependencies sd"""
    )
    links = [dict(row) for row in await cursor.fetchall()]

    return {
        "data": {"nodes": nodes, "links": links},
        "error": None,
        "meta": None,
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
