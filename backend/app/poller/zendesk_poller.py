"""Zendesk Status API poller.

Fetches active incidents from status.zendesk.com/api/incidents/active
and maps to our status model.
"""

import logging

import httpx

from app.poller.normalizer import ServiceStatus
from app.poller.statuspage_poller import PollResult

logger = logging.getLogger(__name__)


async def poll_zendesk(
    client: httpx.AsyncClient,
    poll_url: str,
) -> PollResult:
    """Poll the Zendesk Status API for active incidents.

    Returns { data: [...incidents], included: [...] }.
    Empty data array means operational.
    """
    try:
        response = await client.get(poll_url)
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as e:
        logger.warning("HTTP %d from Zendesk status: %s", e.response.status_code, e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=f"HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        logger.warning("Request error polling Zendesk status: %s", e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e))
    except Exception as e:
        logger.warning("Unexpected error polling Zendesk status: %s", e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e))

    incidents = body.get("data", [])

    if not incidents:
        return PollResult(
            status=ServiceStatus.OPERATIONAL,
            page_name="Zendesk",
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
        page_name="Zendesk",
        incidents=incidents,
    )
