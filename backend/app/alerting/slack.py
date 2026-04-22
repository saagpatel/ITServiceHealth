"""Slack Block Kit alerting via incoming webhooks.

Builds rich message payloads and sends them to a Slack channel.
Handles rate limiting (1 msg/sec) and batching (>3 changes).
"""

import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger(__name__)

RETRY_AFTER_DEFAULT = 2
RETRY_AFTER_MAX = 60


def _parse_retry_after(raw: str | None) -> int:
    """Parse an HTTP Retry-After header into seconds.

    Accepts integer seconds or HTTP-date format (RFC 7231). Always returns a
    positive int capped at RETRY_AFTER_MAX so a malicious or misformed header
    can't stall us for hours.
    """
    if not raw:
        return RETRY_AFTER_DEFAULT
    raw = raw.strip()
    try:
        seconds = int(raw)
    except ValueError:
        try:
            target = parsedate_to_datetime(raw)
            now = datetime.now(timezone.utc)
            seconds = int((target - now).total_seconds())
        except (TypeError, ValueError):
            return RETRY_AFTER_DEFAULT
    if seconds <= 0:
        return RETRY_AFTER_DEFAULT
    return min(seconds, RETRY_AFTER_MAX)

EMOJI_MAP = {
    "operational": "\u2705",
    "degraded": "\U0001f7e1",
    "partial_outage": "\U0001f7e0",
    "major_outage": "\U0001f534",
    "unknown": "\u26ab",
}


def _format_status(status: str) -> str:
    """Format a status string for display: 'partial_outage' → 'Partial Outage'."""
    return status.replace("_", " ").title()


def build_slack_alert(
    service_name: str,
    old_status: str,
    new_status: str,
    impact_statement: str,
    status_page_url: str | None,
) -> dict:
    """Build a Slack Block Kit payload for a single status change."""
    emoji = EMOJI_MAP.get(new_status, "\u26ab")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {service_name} Status Change",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Previous:*\n{_format_status(old_status)}"},
                {"type": "mrkdwn", "text": f"*Current:*\n{_format_status(new_status)}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Impact:*\n{impact_statement}"},
        },
    ]

    if status_page_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "View Status Page"},
                "url": status_page_url,
                "action_id": "view_status_page",
            }],
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"IT Service Health Dashboard \u2022 {now}"}],
    })

    return {
        "text": f"{emoji} {service_name}: {_format_status(old_status)} \u2192 {_format_status(new_status)}",
        "blocks": blocks,
    }


def build_batch_slack_alert(
    changes: list[tuple[str, str, str, str, str | None]],
) -> dict:
    """Build a single Slack message for multiple status changes.

    Args:
        changes: List of (service_name, old_status, new_status, impact_statement, status_page_url).
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"\U0001f6a8 {len(changes)} Service Status Changes",
                "emoji": True,
            },
        },
    ]

    for service_name, old_status, new_status, impact_statement, status_page_url in changes:
        emoji = EMOJI_MAP.get(new_status, "\u26ab")
        text = (
            f"{emoji} *{service_name}*: {_format_status(old_status)} \u2192 {_format_status(new_status)}\n"
            f"{impact_statement}"
        )
        if status_page_url:
            text += f"\n<{status_page_url}|View Status Page>"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"IT Service Health Dashboard \u2022 {now}"}],
    })

    fallback = ", ".join(
        f"{name}: {_format_status(old)} \u2192 {_format_status(new)}"
        for name, old, new, _, _ in changes
    )

    return {
        "text": f"\U0001f6a8 {len(changes)} status changes: {fallback}",
        "blocks": blocks,
    }


async def send_slack_alert(
    webhook_url: str,
    payload: dict,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Send a Slack Block Kit payload to a webhook URL.

    Handles 429 rate limiting with one retry. Never raises — returns bool.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=10.0)

    try:
        response = await client.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            return True

        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            logger.warning("Slack rate limited, retrying in %ds", retry_after)
            await asyncio.sleep(retry_after)
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            return response.status_code == 200

        logger.warning("Slack webhook returned %d: %s", response.status_code, response.text[:200])
        return False

    except Exception as e:
        logger.warning("Slack alert failed: %s", e)
        return False
    finally:
        if own_client:
            await client.aclose()
