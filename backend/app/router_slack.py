"""Slack interactivity and slash-command endpoints.

POST /api/slack/interactivity — Phase 2B ack flow.
  Handles block_actions payloads from Slack's interactivity API. When an
  operator clicks "Acknowledge" on a Slack alert, Slack POSTs here with a
  signed payload. We verify the signature, update alert_sent_log, and
  rewrite the original Slack message via the response_url.
  Feature-gated: returns 404 when `SLACK_ACK_ENABLED` is False.

POST /api/slack/slash — Phase 7 slash command.
  Handles /itstatus <service> slash commands from Slack. Looks up current
  status from the DB and returns an ephemeral Block Kit response.
  Feature-gated: returns 503 when `SLACK_SLASH_ENABLED` is False.

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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.alerting.slack import EMOJI_MAP
from app.config import settings
from app.database import get_db, get_write_lock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slack", tags=["slack"])

_TIMESTAMP_TOLERANCE_SECONDS = 300  # 5 minutes
_SLACK_RESPONSE_HOST = "hooks.slack.com"
_SLACK_RESPONSE_PATH_PREFIX = "/actions/"


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


def _slack_response_relative_url(response_url: str) -> str | None:
    """Return a relative Slack response_url path after host allowlisting."""
    parsed = urllib.parse.urlsplit(response_url)
    if not (
        parsed.scheme == "https"
        and parsed.hostname == _SLACK_RESPONSE_HOST
        and parsed.path.startswith(_SLACK_RESPONSE_PATH_PREFIX)
    ):
        return None
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


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

    response_path = _slack_response_relative_url(response_url)
    if response_path is None:
        logger.warning("Skipping invalid Slack response_url")
        return

    try:
        async with httpx.AsyncClient(
            base_url=f"https://{_SLACK_RESPONSE_HOST}",
            timeout=10.0,
        ) as client:
            # Slack host is fixed by base_url; only the allowlisted Slack path is dynamic.
            # codeql[py/full-ssrf]
            resp = await client.post(response_path, json=payload)
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


# ── Slash command helpers ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class _MatchResult:
    kind: Literal["found", "empty", "none", "ambiguous"]
    service: dict[str, Any] | None = None
    candidates: list[str] = field(default_factory=list)


def _match_service(text: str, rows: list[dict[str, Any]]) -> _MatchResult:
    """Match a slash-command query against known services.

    Resolution order:
      1. Empty query → empty
      2. Exact id match (case-insensitive)
      3. Exact display_name match (case-insensitive)
      4. Substring of display_name: unique → found; multiple → ambiguous
      5. Fallback → none
    """
    q = text.strip().lower()
    if not q:
        return _MatchResult(kind="empty")

    # Exact id match
    for row in rows:
        if (row.get("id") or "").lower() == q:
            return _MatchResult(kind="found", service=row)

    # Exact display_name match
    for row in rows:
        if (row.get("display_name") or "").lower() == q:
            return _MatchResult(kind="found", service=row)

    # Substring of display_name
    partial = [row for row in rows if q in (row.get("display_name") or "").lower()]
    if len(partial) == 1:
        return _MatchResult(kind="found", service=partial[0])
    if len(partial) > 1:
        return _MatchResult(
            kind="ambiguous",
            candidates=[row.get("display_name") or row.get("id") or "" for row in partial],
        )

    return _MatchResult(kind="none")


def _human_duration(iso: str | None) -> str:
    """Convert an ISO 8601 timestamp to a human-readable 'N units ago' string."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta = datetime.now(UTC) - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''} ago"
    except (ValueError, TypeError):
        return "—"


def _build_status_message(service: dict[str, Any]) -> dict[str, Any]:
    """Build an ephemeral Block Kit payload for a single service status lookup."""
    effective_status = service.get("current_status") or "unknown"
    if service.get("poller_health") == "broken":
        effective_status = "unknown"

    emoji = EMOJI_MAP.get(effective_status, "⚪")
    status_label = effective_status.replace("_", " ").title()
    display_name = service.get("display_name") or service.get("id") or "Unknown"
    category = service.get("category") or "—"
    tier = service.get("tier") or "—"
    human_duration = _human_duration(service.get("last_status_change_at"))
    status_page_url = service.get("status_page_url")

    section_fields: list[dict[str, str]] = [
        {"type": "mrkdwn", "text": f"*Status:*\n{emoji} {status_label}"},
        {"type": "mrkdwn", "text": f"*Category:*\n{category}"},
        {"type": "mrkdwn", "text": f"*Last change:*\n{human_duration}"},
        {"type": "mrkdwn", "text": f"*Tier:*\n{tier}"},
    ]

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {display_name}"},
        },
        {
            "type": "section",
            "fields": section_fields,
        },
    ]

    if status_page_url:
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"<{status_page_url}|View Status Page>"},
            ],
        })

    return {
        "response_type": "ephemeral",
        "text": f"{display_name}: {status_label}",
        "blocks": blocks,
    }


def _build_empty_message(sample_ids: list[str]) -> dict[str, Any]:
    """Usage hint returned when the slash command is invoked with no text."""
    known = ", ".join(sample_ids[:10])
    text = f"Usage: `/itstatus <service>`. Known services: {known}."
    return {
        "response_type": "ephemeral",
        "text": text,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }


def _build_no_match_message(query: str) -> dict[str, Any]:
    """Returned when no service matches the query."""
    text = f"No service matches `{query}`. See the dashboard for the full list."
    return {
        "response_type": "ephemeral",
        "text": text,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }


def _build_ambiguous_message(query: str, candidates: list[str]) -> dict[str, Any]:
    """Returned when multiple services match the substring query."""
    names = ", ".join(candidates)
    text = f"Multiple services match `{query}`: {names}. Please be more specific."
    return {
        "response_type": "ephemeral",
        "text": text,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }


def _build_unknown_command_message(command: str) -> dict[str, Any]:
    """Returned when a command other than /itstatus is routed here."""
    text = f"Unknown slash command `{command}`. This endpoint handles `/itstatus`."
    return {
        "response_type": "ephemeral",
        "text": text,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }


@router.post("/slash")
async def slack_slash_command(request: Request) -> dict[str, Any]:
    """Handle /itstatus <service> Slack slash commands.

    Returns an ephemeral Block Kit message with the current service status.
    Feature-gated: returns 503 when SLACK_SLASH_ENABLED is False.

    Slack expects a 200 response for all application-level errors (wrong command,
    no match, etc.) — only auth failures should return non-200.
    """
    # Feature gate
    if not settings.slack_slash_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "data": None,
                "error": {
                    "code": "SLASH_NOT_ENABLED",
                    "message": "Slash commands are not enabled.",
                },
                "meta": None,
            },
        )

    if settings.slack_signing_secret is None:
        logger.error("Slack slash command received but SLACK_SIGNING_SECRET is unset")
        raise HTTPException(
            status_code=503,
            detail={
                "data": None,
                "error": {
                    "code": "SLASH_NOT_CONFIGURED",
                    "message": "Slack signing secret is not configured.",
                },
                "meta": None,
            },
        )

    raw_body = await request.body()

    ts_header: str | None = request.headers.get("X-Slack-Request-Timestamp")
    sig_header: str | None = request.headers.get("X-Slack-Signature")

    if not ts_header or not sig_header:
        logger.warning("Slack slash: missing signature headers")
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")

    # Replay protection first (cheap, before HMAC)
    if not _check_slack_timestamp(ts_header):
        logger.warning("Slack slash: stale timestamp %r", ts_header)
        raise HTTPException(status_code=401, detail="Stale request timestamp")

    signing_secret = settings.slack_signing_secret.get_secret_value()
    if not _verify_slack_signature(raw_body, ts_header, sig_header, signing_secret):
        logger.warning("Slack slash: signature mismatch")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse flat x-www-form-urlencoded body (slash commands don't use payload=)
    params = urllib.parse.parse_qs(raw_body.decode())
    command: str = params.get("command", [""])[0]
    text: str = params.get("text", [""])[0]

    if command != "/itstatus":
        return _build_unknown_command_message(command)

    db = await get_db()
    cursor = await db.execute(
        "SELECT id, display_name, category, tier, current_status, poller_health, "
        "last_status_change_at, status_page_url FROM services ORDER BY display_name"
    )
    rows: list[dict[str, Any]] = [dict(r) for r in await cursor.fetchall()]

    match = _match_service(text, rows)
    if match.kind == "found" and match.service is not None:
        return _build_status_message(match.service)
    if match.kind == "empty":
        return _build_empty_message([r["id"] for r in rows[:10]])
    if match.kind == "ambiguous":
        return _build_ambiguous_message(text, match.candidates)
    return _build_no_match_message(text)
