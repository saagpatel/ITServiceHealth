"""Inbound Statuspage subscriber webhook receiver.

Accepts signed webhook payloads from Statuspage.io, verifies the
HMAC-SHA256 signature, maps the payload to our normalized status model,
and feeds the change directly into the DB + alerting pipeline — bypassing
flap suppression because webhooks are authoritative.

Feature-gated: returns 404 when `WEBHOOKS_ENABLED` is False so the route
doesn't reveal its existence to callers when disabled.

Supported payload shapes:
  - component_update: fired when a component's status changes
  - incident: fired when an incident is created, updated, or resolved

Unknown shapes are logged and acknowledged (200) without crashing — webhook
senders treat non-2xx as delivery failures and may retry indefinitely.
"""

import asyncio
import hashlib
import hmac
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog.contextvars
from fastapi import APIRouter, Header, HTTPException, Request

from app.alerting.engine import process_changes
from app.config import settings
from app.database import get_db, get_write_lock
from app.poller.change_detector import StatusChange
from app.poller.normalizer import (
    ServiceStatus,
    normalize_statuspage_component,
    normalize_statuspage_indicator,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Statuspage subscriber webhooks are signed with HMAC-SHA256.
# The signature is hex-encoded and placed in X-Statuspage-Signature.
_HMAC_ALGO = "sha256"

# Reject webhooks whose timestamp header (if present) is older than this.
_TIMESTAMP_TOLERANCE_SECONDS = 300  # 5 minutes


def _verify_signature(raw_body: bytes, secret: str, presented_sig: str) -> bool:
    """Return True iff the HMAC-SHA256 hex digest of raw_body matches presented_sig."""
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, presented_sig.lower())


def _check_timestamp(ts_header: str | None) -> bool:
    """Return True if the timestamp is within the tolerance window.

    Statuspage may or may not send X-Statuspage-Timestamp (ISO 8601 UTC or
    Unix epoch integer). Absent header → accept (don't break non-conforming
    payloads). Present but unparseable → accept (don't break future variants).
    Present and too old → reject.
    """
    if ts_header is None:
        return True
    try:
        # Try Unix timestamp first
        ts = float(ts_header)
        age = datetime.now(UTC).timestamp() - ts
    except ValueError:
        try:
            parsed = datetime.fromisoformat(ts_header.replace("Z", "+00:00"))
            age = (datetime.now(UTC) - parsed).total_seconds()
        except (ValueError, TypeError):
            logger.warning("Unparseable X-Statuspage-Timestamp %r — accepting", ts_header)
            return True
    return age <= _TIMESTAMP_TOLERANCE_SECONDS


def _extract_status_from_payload(payload: dict[str, Any]) -> tuple[ServiceStatus, str | None]:
    """Extract a normalized status + optional detail from a Statuspage webhook body.

    Handles two envelope shapes:
      - component_update: new_status comes from component_update.new_status
      - incident: aggregate status comes from incident.impact (page-level indicator)

    Falls back to UNKNOWN when neither field is present.
    """
    component_update: dict[str, Any] | None = payload.get("component_update")
    incident: dict[str, Any] | None = payload.get("incident")

    if component_update and isinstance(component_update, dict):
        raw_status: str | None = component_update.get("new_status")
        if raw_status:
            return normalize_statuspage_component(raw_status), raw_status

    if incident and isinstance(incident, dict):
        # `impact` maps to the page-level indicator vocabulary
        impact: str | None = incident.get("impact")
        name: str | None = incident.get("name")
        if impact:
            return normalize_statuspage_indicator(impact), name or impact

    return ServiceStatus.UNKNOWN, None


async def _apply_webhook_change(
    db: object,
    write_lock: asyncio.Lock,
    service_id: str,
    service_row: dict[str, Any],
    new_status: ServiceStatus,
    status_detail: str | None,
    source: str = "webhook",
) -> StatusChange | None:
    """Write a confirmed webhook status change directly into DB, bypassing flap suppression.

    Mirrors the committed-change path in `change_detector.detect_changes` but
    skips the pending-state buffer entirely — webhooks are authoritative.

    Returns a StatusChange (for the alerting engine) or None if the status
    didn't change.
    """
    import aiosqlite

    conn: aiosqlite.Connection = db  # type: ignore[assignment]
    old_status: str = service_row["current_status"]

    if new_status.value == old_status:
        logger.debug(
            "Webhook for %s: status unchanged (%s) — no-op", service_id, old_status,
        )
        return None

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with write_lock:
        await conn.execute(
            """UPDATE services
               SET current_status = ?, current_status_detail = ?,
                   last_status_change_at = ?,
                   pending_status = NULL,
                   pending_status_count = 0,
                   pending_status_since = NULL
               WHERE id = ?""",
            (new_status.value, status_detail, now, service_id),
        )
        cursor = await conn.execute(
            """INSERT INTO status_events
               (service_id, previous_status, new_status, vendor_title,
                vendor_detail, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                service_id, old_status, new_status.value,
                None, status_detail, source, now,
            ),
        )
        event_id: int = cursor.lastrowid  # type: ignore[assignment]
        await conn.commit()

    logger.info(
        "Webhook applied: %s %s → %s", service_id, old_status, new_status.value,
    )
    return StatusChange(
        service_id=service_id,
        service_display_name=service_row["display_name"],
        previous_status=old_status,
        new_status=new_status.value,
        status_detail=status_detail,
        poll_type="webhook",
        status_page_url=service_row.get("status_page_url"),
        event_id=event_id,
    )


@router.post("/statuspage/{service_id}")
async def receive_statuspage_webhook(
    service_id: str,
    request: Request,
    x_statuspage_signature: str | None = Header(default=None),
    x_statuspage_timestamp: str | None = Header(default=None),
) -> dict[str, bool]:
    """Accept a Statuspage subscriber webhook for `service_id`.

    Verification order:
      1. Feature gate (webhooks_enabled)
      2. Secret configured
      3. Signature present and valid
      4. Timestamp within tolerance (if header present)
      5. Service exists
      6. Parse payload → normalize → apply → alert
    """
    # 1. Feature gate — return 404 so the endpoint doesn't advertise itself
    if not settings.webhooks_enabled:
        raise HTTPException(status_code=404, detail="Not Found")

    # 2. Secret must be configured
    if settings.statuspage_webhook_secret is None:
        logger.error("Webhook received but STATUSPAGE_WEBHOOK_SECRET is unset")
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    secret = settings.statuspage_webhook_secret.get_secret_value()

    # 3. Signature verification — read raw body to avoid any decoding
    raw_body = await request.body()

    if not x_statuspage_signature:
        logger.warning("Webhook for %s: missing X-Statuspage-Signature", service_id)
        raise HTTPException(status_code=403, detail="Missing signature")

    if not _verify_signature(raw_body, secret, x_statuspage_signature):
        logger.warning("Webhook for %s: signature mismatch", service_id)
        raise HTTPException(status_code=403, detail="Invalid signature")

    # 4. Replay protection via timestamp
    if not _check_timestamp(x_statuspage_timestamp):
        logger.warning(
            "Webhook for %s: stale timestamp %r", service_id, x_statuspage_timestamp,
        )
        raise HTTPException(status_code=403, detail="Stale webhook timestamp")

    # Bind a webhook ID to structlog context so every downstream log line
    # carries it — mirrors the poll_cycle_id pattern used in the scheduler.
    webhook_id = f"wh-{uuid.uuid4().hex[:12]}"
    structlog.contextvars.bind_contextvars(webhook_id=webhook_id)

    try:
        # 5. Verify service exists
        db = await get_db()
        cursor = await db.execute(
            """SELECT id, display_name, current_status, status_page_url
               FROM services WHERE id = ?""",
            (service_id,),
        )
        svc_row = await cursor.fetchone()
        if svc_row is None:
            logger.warning("Webhook for unknown service_id %r", service_id)
            raise HTTPException(status_code=404, detail="Service not found")

        service_row = dict(svc_row)

        # 6. Parse payload
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            logger.warning(
                "Webhook for %s: invalid JSON body — acknowledging anyway", service_id,
            )
            return {"ok": True}

        # Handle Statuspage unsubscribe confirmation pings gracefully
        meta: dict[str, Any] | None = payload.get("meta")
        if isinstance(meta, dict) and meta.get("unsubscribe"):
            logger.info("Webhook unsubscribe confirmation for %s — ack", service_id)
            return {"ok": True}

        new_status, status_detail = _extract_status_from_payload(payload)

        if new_status == ServiceStatus.UNKNOWN:
            # Unknown payload shape — log for visibility but don't crash or error.
            # The sender would retry on non-2xx which could cause alert floods.
            logger.info(
                "Webhook for %s: unrecognised payload shape — no status extracted, ack 200",
                service_id,
            )
            return {"ok": True}

        write_lock = get_write_lock()
        change = await _apply_webhook_change(
            db, write_lock, service_id, service_row, new_status, status_detail,
        )

        if change:
            # Feed into the same alerting pipeline as polled changes.
            # `process_changes` handles impact statements, dedup, and Slack sends.
            http_client = getattr(request.app.state, "http_client", None)
            await process_changes(db, write_lock, [change], http_client=http_client)

        return {"ok": True}

    finally:
        structlog.contextvars.unbind_contextvars("webhook_id")
