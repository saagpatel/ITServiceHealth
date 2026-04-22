"""Slack Status API poller.

Fetches current status from slack-status.com/api/v2.0.0/current
and returns normalized status data.

The Slack API can return two formats:
- Dict: the normal /current response with {status, active_incidents, ...}
- List: a redirect to the history endpoint returning incident objects.
  Each incident has {id, status, type, title, ...} where status is
  "active", "resolved", "scheduled", "completed", or "cancelled",
  and type is "outage", "incident", "notice", or "maintenance".
"""

import logging

import httpx

from app.poller.normalizer import ServiceStatus, normalize_slack_status
from app.poller.resilience import describe_fetch_error, resilient_fetch
from app.poller.statuspage_poller import PollResult

logger = logging.getLogger(__name__)

# Slack incident type → severity rank (higher = worse)
_SLACK_TYPE_RANK = {
    "outage": ServiceStatus.MAJOR_OUTAGE,
    "incident": ServiceStatus.PARTIAL_OUTAGE,
    "notice": ServiceStatus.DEGRADED,
    "maintenance": ServiceStatus.DEGRADED,
}


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
        # resilient_fetch handles retries + per-host breaker. The explicit
        # Accept header is from the origin branch so slack-status.com
        # returns JSON not HTML when redirects land us on a different doc.
        response = await resilient_fetch(
            client, poll_url, headers={"Accept": "application/json"},
        )
        data = response.json()
    except Exception as e:
        detail, reason = describe_fetch_error(e)
        logger.warning("Slack poll failed: %s (%s)", detail, reason)
        return PollResult(
            status=ServiceStatus.UNKNOWN,
            status_detail=detail,
            poll_failure_reason=reason,
        )

    # Normal dict response — use the existing normalizer
    if isinstance(data, dict):
        status = normalize_slack_status(data)
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

    # List response — redirect to history endpoint. Each item is an incident dict
    # with a "status" field (active/resolved/etc) and "type" (outage/incident/etc).
    if isinstance(data, list):
        active_incidents = [
            item for item in data
            if isinstance(item, dict) and item.get("status") == "active"
        ]

        if not active_incidents:
            return PollResult(
                status=ServiceStatus.OPERATIONAL,
                status_detail=None,
                page_name="Slack",
                incidents=[],
                scheduled_maintenances=[],
            )

        # Find worst severity among active incidents
        worst = ServiceStatus.DEGRADED
        worst_title = None
        severity_rank = {"major_outage": 4, "partial_outage": 3, "degraded": 2}

        for inc in active_incidents:
            inc_type = inc.get("type", "")
            mapped = _SLACK_TYPE_RANK.get(inc_type, ServiceStatus.DEGRADED)
            if severity_rank.get(mapped.value, 0) > severity_rank.get(worst.value, 0):
                worst = mapped
                worst_title = inc.get("title")

        if worst_title is None and active_incidents:
            worst_title = active_incidents[0].get("title")

        logger.info(
            "Slack API returned history list (%d items, %d active) — status: %s",
            len(data), len(active_incidents), worst.value,
        )

        return PollResult(
            status=worst,
            status_detail=worst_title,
            page_name="Slack",
            incidents=active_incidents,
            scheduled_maintenances=[],
        )

    # Unexpected type
    logger.warning("Slack API returned unexpected type: %s", type(data).__name__)
    return PollResult(status=ServiceStatus.UNKNOWN, status_detail="Unexpected response format")
