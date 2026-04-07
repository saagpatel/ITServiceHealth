"""Timeline API route: chronological feed of status change events."""

from datetime import datetime

from fastapi import APIRouter

from app.database import get_db

router = APIRouter(prefix="/api", tags=["timeline"])


@router.get("/timeline")
async def get_timeline(
    limit: int = 50,
    service_id: str | None = None,
) -> dict:
    """Get recent status events, newest first."""
    db = await get_db()

    # Clamp limit
    limit = max(1, min(limit, 200))

    # Count total
    if service_id:
        cursor = await db.execute(
            "SELECT count(*) FROM status_events WHERE service_id = ?",
            (service_id,),
        )
    else:
        cursor = await db.execute("SELECT count(*) FROM status_events")
    total = (await cursor.fetchone())[0]

    # Fetch events
    if service_id:
        cursor = await db.execute(
            """SELECT se.id, se.service_id, s.display_name as service_name,
                      se.previous_status, se.new_status, se.vendor_title, se.vendor_detail,
                      se.impact_statement, se.source, se.created_at
               FROM status_events se
               JOIN services s ON s.id = se.service_id
               WHERE se.service_id = ?
               ORDER BY se.created_at DESC LIMIT ?""",
            (service_id, limit),
        )
    else:
        cursor = await db.execute(
            """SELECT se.id, se.service_id, s.display_name as service_name,
                      se.previous_status, se.new_status, se.vendor_title, se.vendor_detail,
                      se.impact_statement, se.source, se.created_at
               FROM status_events se
               JOIN services s ON s.id = se.service_id
               ORDER BY se.created_at DESC LIMIT ?""",
            (limit,),
        )

    events = [dict(r) for r in await cursor.fetchall()]

    return {
        "data": {"events": events, "total": total},
        "error": None,
        "meta": {"limit": limit, "service_id_filter": service_id},
    }


@router.get("/timeline/clustered")
async def get_timeline_clustered(
    window: int = 300,
    limit: int = 100,
) -> dict:
    """Get timeline events grouped into incident clusters.

    Events within `window` seconds of each other are grouped.
    Dependency-aware root cause detection identifies the probable upstream trigger.
    """
    db = await get_db()
    window = max(60, min(window, 3600))
    limit = max(1, min(limit, 500))

    # Fetch events (exclude boot warmup)
    cursor = await db.execute(
        """SELECT se.id, se.service_id, s.display_name as service_name,
                  se.previous_status, se.new_status, se.vendor_title, se.vendor_detail,
                  se.impact_statement, se.source, se.created_at
           FROM status_events se
           JOIN services s ON s.id = se.service_id
           WHERE NOT (se.previous_status = 'unknown' AND se.new_status = 'operational')
           ORDER BY se.created_at DESC LIMIT ?""",
        (limit,),
    )
    events = [dict(r) for r in await cursor.fetchall()]
    events.reverse()  # oldest first for clustering

    if not events:
        return {
            "data": {"clusters": [], "total_clusters": 0, "total_events": 0},
            "error": None,
            "meta": {"window": window},
        }

    # Load dependency graph for root cause detection
    cursor = await db.execute(
        "SELECT upstream_service_id, downstream_service_id FROM service_dependencies"
    )
    dep_rows = await cursor.fetchall()
    downstream_map: dict[str, set[str]] = {}
    for row in dep_rows:
        up, down = row[0], row[1]
        if up not in downstream_map:
            downstream_map[up] = set()
        downstream_map[up].add(down)

    # Layer 1: Time-window clustering
    clusters = []
    current_cluster: list[dict] = []

    for event in events:
        event_time = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))

        if current_cluster:
            last_time = datetime.fromisoformat(
                current_cluster[-1]["created_at"].replace("Z", "+00:00")
            )
            gap = (event_time - last_time).total_seconds()
            if gap > window:
                clusters.append(_finalize_cluster(current_cluster, downstream_map))
                current_cluster = []

        current_cluster.append(event)

    if current_cluster:
        clusters.append(_finalize_cluster(current_cluster, downstream_map))

    # Reverse so newest clusters first
    clusters.reverse()

    return {
        "data": {
            "clusters": clusters,
            "total_clusters": len(clusters),
            "total_events": len(events),
        },
        "error": None,
        "meta": {"window": window},
    }


SEVERITY_RANK = {
    "major_outage": 4,
    "partial_outage": 3,
    "degraded": 2,
    "operational": 1,
    "unknown": 0,
}


def _finalize_cluster(events: list[dict], downstream_map: dict[str, set[str]]) -> dict:
    """Finalize a cluster: detect root cause, compute severity."""
    service_ids = {e["service_id"] for e in events}
    unique_services = {e["service_id"]: e["service_name"] for e in events}

    # Layer 2: Dependency-aware root cause
    root_cause_id = None
    root_cause_name = None
    best_score = 0

    for sid in service_ids:
        downstream = downstream_map.get(sid, set())
        overlap = len(downstream & service_ids)
        if overlap > best_score:
            best_score = overlap
            root_cause_id = sid
            root_cause_name = unique_services.get(sid)

    # Worst severity in the cluster
    worst = max(events, key=lambda e: SEVERITY_RANK.get(e["new_status"], 0))

    return {
        "root_cause": {"id": root_cause_id, "name": root_cause_name} if root_cause_id else None,
        "severity": worst["new_status"],
        "started_at": events[0]["created_at"],
        "ended_at": events[-1]["created_at"],
        "service_count": len(unique_services),
        "event_count": len(events),
        "events": list(reversed(events)),  # newest first within cluster
    }
