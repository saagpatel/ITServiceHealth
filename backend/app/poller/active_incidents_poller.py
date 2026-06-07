"""Active incidents API poller.

Fetches active incidents from a JSON incidents endpoint and maps to
our status model. The response envelope wraps incident objects under
a "data" key; an empty array means operational.
"""

import logging

import httpx

from app.poller.normalizer import ServiceStatus
from app.poller.resilience import describe_fetch_error, resilient_fetch
from app.poller.statuspage_poller import PollResult

logger = logging.getLogger(__name__)


async def poll_active_incidents(
    client: httpx.AsyncClient,
    poll_url: str,
) -> PollResult:
    """Poll an active-incidents JSON endpoint.

    Returns { data: [...incidents], included: [...] }.
    Empty data array means operational.
    """
    try:
        response = await resilient_fetch(client, poll_url)
        body = response.json()
    except Exception as e:
        detail, reason = describe_fetch_error(e)
        logger.warning("Active-incidents poll failed: %s (%s)", detail, reason)
        return PollResult(
            status=ServiceStatus.UNKNOWN,
            status_detail=detail,
            poll_failure_reason=reason,
        )

    incidents = body.get("data", [])

    if not incidents:
        return PollResult(
            status=ServiceStatus.OPERATIONAL,
            page_name="Active Incidents",
            incidents=[],
        )

    # Determine severity from active incidents
    severity = ServiceStatus.DEGRADED
    status_detail = None

    for inc in incidents:
        attrs = inc.get("attributes", {})
        title = attrs.get("title", "")
        impact = attrs.get("impact", "").lower()

        if not status_detail:
            status_detail = title

        if "critical" in impact or "outage" in title.lower():
            severity = ServiceStatus.MAJOR_OUTAGE
            status_detail = title
            break
        if "major" in impact or "partial" in title.lower():
            severity = ServiceStatus.PARTIAL_OUTAGE
            status_detail = title

    return PollResult(
        status=severity,
        status_detail=status_detail,
        page_name="Active Incidents",
        incidents=incidents,
    )
