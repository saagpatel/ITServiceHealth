"""Admin API router: manual status updates for services without automated polling.

All endpoints require a bearer token (`ADMIN_API_TOKEN` env var). Manual updates
are audited: `updated_by`, `reason`, and `client_ip` are written to `status_events`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import require_admin_token
from app.database import get_db, get_write_lock
from app.poller.change_detector import apply_manual_update
from app.poller.normalizer import ServiceStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class StatusUpdateRequest(BaseModel):
    service_id: str = Field(min_length=1, max_length=128)
    new_status: ServiceStatus
    detail: str | None = Field(default=None, max_length=2000)
    reason: str = Field(
        min_length=3,
        max_length=500,
        description="Why this manual update is being made — stored in the audit trail.",
    )


@router.post("/status")
async def update_service_status(
    request: Request,
    body: StatusUpdateRequest,
    principal: str = Depends(require_admin_token),
) -> dict:
    """Manually update a service's status.

    Goes through the same change detection path as automated pollers,
    creating a status_event with source='manual' if the status changed.
    Writes `updated_by`, `reason`, and `client_ip` to the event for audit.
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

    client_ip = request.client.host if request.client else None

    try:
        change = await apply_manual_update(
            db,
            write_lock,
            body.service_id,
            body.new_status,
            body.detail,
            updated_by=principal,
            reason=body.reason,
            client_ip=client_ip,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    logger.info(
        "Admin update: service=%s new_status=%s by=%s from=%s",
        body.service_id, body.new_status.value, principal, client_ip,
    )

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
