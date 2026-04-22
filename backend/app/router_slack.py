"""Slack interactivity endpoint for the ack flow (Phase 2B).

Handles block_actions payloads from Slack's interactivity API. When an
operator clicks "Acknowledge" on a Slack alert, Slack POSTs here with a
signed payload. We verify the signature, update alert_sent_log, and
rewrite the original Slack message via the response_url.

Feature-gated: returns 404 when `SLACK_ACK_ENABLED` is False.

Slack signing-secret protocol (v0):
  1. Concatenate: v0:{X-Slack-Request-Timestamp}:{raw_body}
  2. HMAC-SHA256 with SLACK_SIGNING_SECRET
  3. Prefix with "v0="
  4. Compare to X-Slack-Signature with compare_digest (constant time)
"""

import hashlib
import hmac
import json
import logging
import urllib.parse
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.database import get_db, get_write_lock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slack", tags=["slack"])

_TIMESTAMP_TOLERANCE_SECONDS = 300  # 5 minutes


def _verify_slack_signature(
    raw_body: bytes,
    timestamp: str,
    presented_sig: str,
    secret: str,
) -> bool:
    """Verify a Slack v0 signature against raw_body + timestamp."""
    base = f"v0:{timestamp}:{raw_body.decode()}"
    expected = "v0=" + hmac.new(
        secret.encode(), base.encode(), hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, presented_sig)


def _check_slack_timestamp(timestamp: str) -> bool:
    """Return True iff the Slack request timestamp is within tolerance."""
    try:
        ts = float(timestamp)
        age = datetime.now(UTC).timestamp() - ts
        return age <= _TIMESTAMP_TOLERANCE_SECONDS
    except (ValueError, TypeError):
        logger.warning("Unparseable X-Slack-Request-Timestamp %r", timestamp)
        return False


async def _update_ack(
    db: Any,
    write_lock: Any,
    dedup_key: str,
    username: str,
) -> bool:
    """Set acknowledged_at + acknowledged_by on the most-recent unresolved alert row.

    Returns True if a row was updated, False if none matched.
    """
    import aiosqlite

    conn: aiosqlite.Connection = db
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with write_lock:
        cursor = await conn.execute(
            """SELECT id FROM alert_sent_log
               WHERE dedup_key = ?
                 AND suppressed_by IS NULL
                 AND acknowledged_at IS NULL
               ORDER BY id DESC LIMIT 1""",
            (dedup_key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return False

        await conn.execute(
            """UPDATE alert_sent_log
               SET acknowledged_at = ?, acknowledged_by = ?
               WHERE id = ?""",
            (now, username, row["id"]),
        )
        await conn.commit()

    return True


async def _post_response_url(
    response_url: str,
    original_blocks: list[dict[str, Any]],
    username: str,
) -> None:
    """Replace the original Slack message with an ack'd version.

    Appends a context block noting who acked and when, then POSTs to
    Slack's response_url with replace_original=true.
    """
    now_str = datetime.now(UTC).strftime("%H:%M UTC")
    ack_block: dict[str, Any] = {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"\u2713 Acknowledged by @{username} at {now_str}",
            }
        ],
    }

    # Clone blocks and remove any existing ack_alert actions block to avoid
    # duplicate Acknowledge buttons if Slack retries and we re-ack.
    updated_blocks = [
        b for b in original_blocks
        if not (
            b.get("type") == "actions"
            and any(
                e.get("action_id") == "ack_alert"
                for e in b.get("elements", [])
            )
        )
    ]
    updated_blocks.append(ack_block)

    payload = {
        "replace_original": True,
        "blocks": updated_blocks,
        "text": f"\u2713 Acknowledged by @{username} at {now_str}",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(response_url, json=payload)
            if resp.status_code != 200:
                logger.warning(
                    "Slack response_url returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
    except Exception:
        logger.exception("Failed to POST to Slack response_url")


@router.post("/interactivity")
async def slack_interactivity(request: Request) -> dict[str, str]:
    """Handle Slack block_actions interactivity payloads.

    Slack POSTs application/x-www-form-urlencoded with a `payload=` field.
    We verify the signature, parse the payload, and process ack_alert actions.
    """
    # Feature gate
    if not settings.slack_ack_enabled:
        raise HTTPException(status_code=404, detail="Not Found")

    if settings.slack_signing_secret is None:
        logger.error("Slack interactivity received but SLACK_SIGNING_SECRET is unset")
        raise HTTPException(status_code=503, detail="Slack signing secret not configured")

    raw_body = await request.body()

    # Extract signature headers
    ts_header: str | None = request.headers.get("X-Slack-Request-Timestamp")
    sig_header: str | None = request.headers.get("X-Slack-Signature")

    if not ts_header or not sig_header:
        logger.warning("Slack interactivity: missing signature headers")
        raise HTTPException(status_code=403, detail="Missing Slack signature headers")

    # Replay protection first (cheap, before HMAC)
    if not _check_slack_timestamp(ts_header):
        logger.warning("Slack interactivity: stale timestamp %r", ts_header)
        raise HTTPException(status_code=403, detail="Stale request timestamp")

    signing_secret = settings.slack_signing_secret.get_secret_value()
    if not _verify_slack_signature(raw_body, ts_header, sig_header, signing_secret):
        logger.warning("Slack interactivity: signature mismatch")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Parse the form-encoded body to extract the JSON payload field
    try:
        parsed = urllib.parse.parse_qs(raw_body.decode())
        payload_json = parsed.get("payload", [""])[0]
        slack_payload: dict[str, Any] = json.loads(payload_json)
    except (ValueError, KeyError, IndexError):
        logger.warning("Slack interactivity: malformed payload body")
        return {}

    # We only handle block_actions; silently ignore other types (e.g., shortcuts,
    # view_submission) so Slack doesn't get a confusing error response.
    payload_type: str = slack_payload.get("type", "")
    if payload_type != "block_actions":
        logger.debug("Slack interactivity: unhandled payload type %r — ignoring", payload_type)
        return {}

    actions: list[dict[str, Any]] = slack_payload.get("actions", [])
    if not actions:
        return {}

    action = actions[0]
    if action.get("action_id") != "ack_alert":
        logger.debug(
            "Slack interactivity: unhandled action_id %r — ignoring",
            action.get("action_id"),
        )
        return {}

    dedup_key: str = action.get("value", "")
    user_info: dict[str, Any] = slack_payload.get("user", {})
    username: str = user_info.get("username") or user_info.get("id") or "unknown"
    response_url: str | None = slack_payload.get("response_url")

    db = await get_db()
    write_lock = get_write_lock()

    updated = await _update_ack(db, write_lock, dedup_key, username)
    if not updated:
        logger.info(
            "Ack for dedup_key %r from %s: no matching unresolved alert found",
            dedup_key, username,
        )
        # Still return 200 — Slack would retry on non-2xx
        return {}

    logger.info("Ack recorded: dedup_key=%r by=%s", dedup_key, username)

    # Update the Slack message in-place if we have a response_url
    if response_url:
        original_blocks: list[dict[str, Any]] = (
            slack_payload.get("message", {}).get("blocks", [])
        )
        await _post_response_url(response_url, original_blocks, username)

    # Return empty body — Slack spec says 200 with empty body or {"ok": true}
    return {}
