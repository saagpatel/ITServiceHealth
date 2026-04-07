"""Timeline API route: chronological feed of status change events."""

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
