"""Slack Status API poller.

Fetches current status from slack-status.com/api/v2.0.0/current
and returns normalized status data.
"""

import logging

import httpx

from app.poller.normalizer import ServiceStatus, normalize_slack_status
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
        response = await client.get(poll_url)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as e:
        logger.warning("HTTP %d from Slack status: %s", e.response.status_code, e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=f"HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        logger.warning("Request error polling Slack status: %s", e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e))
    except Exception as e:
        logger.warning("Unexpected error polling Slack status: %s", e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e))

    if not isinstance(data, dict):
        logger.warning("Slack API returned non-dict response: %s", type(data).__name__)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail="Unexpected response format")

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
