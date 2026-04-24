"""Service API routes: list all services, get service detail with dependencies."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException

from app.alerting.burn_rate import BurnRateBreach, evaluate_burn_rate
from app.config import settings
from app.database import get_db
from app.dependencies.graph import get_downstream, get_upstream
from app.sla import compute_error_budget_remaining, compute_uptime

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
                      tier, pending_status, pending_status_count, pending_status_since
               FROM services WHERE category = ? ORDER BY category, display_name""",
            (category,),
        )
    else:
        cursor = await db.execute(
            """SELECT id, display_name, category, current_status, current_status_detail,
                      poll_type, status_page_url, last_polled_at, last_status_change_at,
                      consecutive_failures, last_success_at, last_failure_reason, poller_health,
                      tier, pending_status, pending_status_count, pending_status_since
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
    now = datetime.now(UTC)

    # Collect service IDs that have events (same set as before).
    cursor = await db.execute(
        """SELECT DISTINCT service_id FROM status_events
           WHERE NOT (previous_status = 'unknown' AND new_status = 'operational')"""
    )
    service_ids = [row[0] for row in await cursor.fetchall()]

    results: dict[str, dict[str, float | None]] = {}

    for window_label, window_days in [("uptime_24h", 1), ("uptime_7d", 7), ("uptime_30d", 30)]:
        window_start = now - timedelta(days=window_days)
        for sid in service_ids:
            uptime = await compute_uptime(db, sid, window_start, now)
            if sid not in results:
                results[sid] = {"uptime_24h": None, "uptime_7d": None, "uptime_30d": None}
            if uptime.uptime_percent is not None:
                results[sid][window_label] = uptime.uptime_percent

    return {
        "data": {"services": results},
        "error": None,
        "meta": None,
    }


@router.get("/services/sla/history")
async def get_sla_history(days: int = 30) -> dict:
    """Get daily uptime percentages for each service over N days."""
    db = await get_db()
    days = max(1, min(days, 90))

    now = datetime.now(UTC)
    day_list = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]

    # Collect service IDs that have events in the window (preserves the same
    # set of services that appeared in the old response).
    window_start_overall = now - timedelta(days=days)
    cursor = await db.execute(
        """SELECT DISTINCT service_id FROM status_events
           WHERE created_at >= ?
             AND NOT (previous_status = 'unknown' AND new_status = 'operational')""",
        (window_start_overall.isoformat(),),
    )
    service_ids = [row[0] for row in await cursor.fetchall()]

    services_data: dict[str, list[dict]] = {}

    for sid in service_ids:
        points = []
        for i in range(days - 1, -1, -1):
            # Calendar day matching day_list entry: (now - timedelta(days=i)).date()
            day_dt = now - timedelta(days=i)
            day_key = day_dt.strftime("%Y-%m-%d")
            day_start = day_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            uptime = await compute_uptime(db, sid, day_start, day_end)
            points.append({"date": day_key, "uptime": uptime.uptime_percent})

        services_data[sid] = points

    return {
        "data": {"days": day_list, "services": services_data},
        "error": None,
        "meta": {"days_requested": days},
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


@router.get("/services/slo")
async def get_services_slo() -> dict:
    """Per-service SLO snapshot: error budget remaining + any active burn-rate breaches.

    Unlike the scheduled burn-rate cycle which routes Slack alerts, this endpoint
    reads fresh state synchronously for display consumers (the SLO fuel-gauge view).
    """
    db = await get_db()
    now = datetime.now(UTC)
    target = settings.slo_target_percent

    cursor = await db.execute(
        "SELECT id, display_name, category, tier, current_status, poller_health "
        "FROM services ORDER BY display_name"
    )
    rows = await cursor.fetchall()

    services_out: list[dict] = []
    for row in rows:
        service_id = row["id"]
        service_name = row["display_name"] or service_id

        w30d_start = now - timedelta(days=30)
        w30d = await compute_uptime(db, service_id, w30d_start, now)

        breaches = await evaluate_burn_rate(db, service_id, service_name, now)
        fast_breach = next((b for b in breaches if b.severity == "fast"), None)
        slow_breach = next((b for b in breaches if b.severity == "slow"), None)

        budget_remaining = compute_error_budget_remaining(w30d.uptime_percent, target)

        services_out.append({
            "id": service_id,
            "display_name": service_name,
            "category": row["category"],
            "tier": row["tier"],
            "current_status": row["current_status"],
            "poller_health": row["poller_health"],
            "uptime_30d_pct": w30d.uptime_percent,
            "error_budget_remaining_pct": round(budget_remaining, 2),
            "fast_burning": fast_breach is not None,
            "slow_burning": slow_breach is not None,
            "fast_breach": _breach_to_dict(fast_breach) if fast_breach else None,
            "slow_breach": _breach_to_dict(slow_breach) if slow_breach else None,
        })

    return {
        "data": {
            "services": services_out,
            "thresholds": {
                "target_percent": target,
                "fast_threshold": settings.slo_burn_rate_fast_threshold,
                "slow_threshold": settings.slo_burn_rate_slow_threshold,
            },
        },
        "error": None,
        "meta": None,
    }


def _breach_to_dict(breach: BurnRateBreach) -> dict:
    return {
        "long_window_burn_rate": breach.long_window_burn_rate,
        "short_window_burn_rate": breach.short_window_burn_rate,
        "long_window_label": breach.long_window_label,
        "short_window_label": breach.short_window_label,
    }


@router.get("/services/{service_id}")
async def get_service_detail(service_id: str) -> dict:
    """Get a single service with dependencies and recent events."""
    db = await get_db()

    cursor = await db.execute(
        """SELECT id, display_name, category, current_status, current_status_detail,
                  poll_type, status_page_url, last_polled_at, last_status_change_at,
                  pending_status, pending_status_count, pending_status_since
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
