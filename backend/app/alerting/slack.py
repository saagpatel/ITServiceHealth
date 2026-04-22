"""Slack Block Kit alerting via incoming webhooks.

Builds rich message payloads and sends them to a Slack channel.
Handles rate limiting (1 msg/sec) and batching (>3 changes).
"""

import asyncio
import logging
from datetime import UTC, datetime
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
            now = datetime.now(UTC)
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
    mention: str | None = None,
) -> dict:
    """Build a Slack Block Kit payload for a single status change.

    `mention` is prepended to the impact section when set (e.g., `<!here>`
    for critical-tier services). Empty strings or None mean no mention.
    """
    emoji = EMOJI_MAP.get(new_status, "\u26ab")
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    impact_body = (
        f"{mention} {impact_statement}".strip() if mention else impact_statement
    )

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
            "text": {"type": "mrkdwn", "text": f"*Impact:*\n{impact_body}"},
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
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

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


def build_aggregated_upstream_alert(
    upstream_change,                          # StatusChange for the upstream
    dependents: list,                         # list[StatusChange] for affected downstream
    impact_statement: str,
    mention: str | None = None,
) -> dict:
    """Render a single Slack message that consolidates an upstream outage
    with all downstream services impacted in the same poll cycle.

    Prevents the "Okta down + 20 services alert" thundering herd by rolling
    the dependents into one message citing them all.
    """
    emoji = EMOJI_MAP.get(upstream_change.new_status, "\u26ab")
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    dep_names = [d.service_display_name for d in dependents]

    impact_body = (
        f"{mention} {impact_statement}".strip() if mention else impact_statement
    )

    header_text = (
        f"{emoji} {upstream_change.service_display_name} "
        f"{_format_status(upstream_change.new_status)} "
        f"— {len(dep_names)} dependent service(s) affected"
    )

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Impact:*\n{impact_body}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Dependent services affected:*\n"
                    + "\n".join(f"\u2022 {n}" for n in dep_names[:20])
                    + (f"\n_…and {len(dep_names) - 20} more_" if len(dep_names) > 20 else "")
                ),
            },
        },
    ]

    if upstream_change.status_page_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "View Status Page"},
                "url": upstream_change.status_page_url,
                "action_id": "view_upstream_status_page",
            }],
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": (
                f"IT Service Health Dashboard \u2022 Aggregated upstream alert "
                f"\u2022 {now}"
            ),
        }],
    })

    fallback = (
        f"{emoji} {upstream_change.service_display_name}: "
        f"{_format_status(upstream_change.previous_status)} \u2192 "
        f"{_format_status(upstream_change.new_status)} "
        f"({len(dep_names)} dependents impacted)"
    )
    return {"text": fallback, "blocks": blocks}


def build_poller_health_alert(
    health_change,  # app.poller.change_detector.PollerHealthChange
    using_fallback: bool = False,
) -> dict:
    """Build a Slack Block Kit payload for a poller-health transition.

    Tagged with a wrench emoji and a clear "POLLER HEALTH" header so
    responders never mistake it for a vendor-outage alert, even when
    the alert lands in the main Slack channel due to missing config.
    """
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    going_broken = health_change.new_health == "broken"

    if going_broken:
        header_text = f"\U0001f527 Poller BROKEN — {health_change.service_display_name}"
        summary = (
            f"The poller for *{health_change.service_display_name}* has failed "
            f"{health_change.consecutive_failures} times in a row and is now "
            f"reporting as broken. The dashboard will show this service as "
            f"*unknown* until the poller recovers."
        )
        reason = health_change.failure_reason or "unknown"
    else:
        header_text = f"\u2705 Poller RECOVERED — {health_change.service_display_name}"
        summary = (
            f"The poller for *{health_change.service_display_name}* is back to "
            f"healthy after previously being broken. Status readings for this "
            f"service can be trusted again."
        )
        reason = None

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_text,
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": summary},
        },
    ]

    if reason:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Failure reason:*\n`{reason}`"},
        })

    if using_fallback:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": (
                    ":information_source: Routed to the main alerting channel. "
                    "Set `POLLER_HEALTH_SLACK_WEBHOOK_URL` for a dedicated channel."
                ),
            }],
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"IT Service Health Dashboard \u2022 Poller Health \u2022 {now}",
        }],
    })

    fallback = (
        f"Poller {'BROKEN' if going_broken else 'RECOVERED'}: "
        f"{health_change.service_display_name}"
    )
    return {"text": fallback, "blocks": blocks}


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
