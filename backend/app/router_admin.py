"""Admin API router: manual status updates for services without automated polling."""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.database import get_db, get_write_lock
from app.poller.change_detector import apply_manual_update
from app.poller.normalizer import ServiceStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class StatusUpdateRequest(BaseModel):
    service_id: str
    new_status: ServiceStatus
    detail: str | None = None


@router.post("/status")
async def update_service_status(request: Request, body: StatusUpdateRequest) -> dict:
    """Manually update a service's status.

    Goes through the same change detection path as automated pollers,
    creating a status_event with source='manual' if the status changed.
    """
    db = await get_db()
    write_lock = get_write_lock()

    # Verify service exists
    cursor = await db.execute(
        "SELECT id, display_name FROM services WHERE id = ?",
        (body.service_id,),
    )
    svc = await cursor.fetchone()
    if not svc:
        raise HTTPException(
            status_code=404,
            detail={
                "data": None,
                "error": {
                    "code": "SERVICE_NOT_FOUND",
                    "message": f"Service '{body.service_id}' not found",
                },
                "meta": None,
            },
        )

    try:
        change = await apply_manual_update(
            db, write_lock, body.service_id, body.new_status, body.detail,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Process alerting (impact statement + Slack)
    if change is not None:
        from app.alerting.engine import process_changes
        http_client = getattr(request.app.state, "http_client", None)
        await process_changes(
            db, write_lock, [change],
            http_client=http_client,
        )

    # Fetch updated service
    cursor = await db.execute("SELECT * FROM services WHERE id = ?", (body.service_id,))
    updated = dict(await cursor.fetchone())

    return {
        "data": updated,
        "error": None,
        "meta": {
            "status_changed": change is not None,
            "previous_status": change.previous_status if change else updated["current_status"],
        },
    }
