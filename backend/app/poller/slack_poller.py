"""Slack Status API poller.

Fetches current status from slack-status.com/api/v2.0.0/current
and returns normalized status data.
"""

import logging

import httpx

from app.poller.normalizer import ServiceStatus, normalize_slack_status
from app.poller.resilience import describe_fetch_error, resilient_fetch
from app.poller.statuspage_poller import PollResult

logger = logging.getLogger(__name__)


async def poll_slack(
    client: httpx.AsyncClient,
    poll_url: str,
) -> PollResult:
    """Poll the Slack Status API.

    Args:
        client: Shared httpx AsyncClient.
        poll_url: Slack status API URL.

    Returns:
        PollResult with normalized status.
    """
    try:
        response = await resilient_fetch(client, poll_url)
        data = response.json()
    except Exception as e:
        detail, reason = describe_fetch_error(e)
        logger.warning("Slack poll failed: %s (%s)", detail, reason)
        return PollResult(
            status=ServiceStatus.UNKNOWN,
            status_detail=detail,
            poll_failure_reason=reason,
        )

    if not isinstance(data, dict):
        logger.warning("Slack API returned non-dict response: %s", type(data).__name__)
        return PollResult(
            status=ServiceStatus.UNKNOWN,
            status_detail="Unexpected response format",
            poll_failure_reason=f"parse_error: expected dict, got {type(data).__name__}",
        )

    status = normalize_slack_status(data)

    # Extract detail from first active incident title
    status_detail = None
    active = data.get("active_incidents", [])
    if active and isinstance(active[0], dict):
        status_detail = active[0].get("title")

    return PollResult(
        status=status,
        status_detail=status_detail,
        page_name="Slack",
        incidents=active,
        scheduled_maintenances=[],
    )
