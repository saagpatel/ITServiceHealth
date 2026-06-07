"""Trust incidents API poller.

Fetches active incidents from a trust/incidents JSON endpoint and maps
to our status model. The endpoint returns a list of incident objects;
entries without a resolved timestamp are considered active.
"""

import logging

import httpx

from app.poller.normalizer import ServiceStatus
from app.poller.resilience import describe_fetch_error, resilient_fetch
from app.poller.statuspage_poller import PollResult

logger = logging.getLogger(__name__)


async def poll_trust_incidents(
    client: httpx.AsyncClient,
    poll_url: str,
) -> PollResult:
    """Poll a trust-incidents JSON endpoint for active incidents.

    The endpoint returns a list of incident objects. If any are active
    (no resolvedAt), the service is degraded/outaged.
    """
    try:
        response = await resilient_fetch(client, poll_url)
        incidents = response.json()
    except Exception as e:
        detail, reason = describe_fetch_error(e)
        logger.warning("Trust-incidents poll failed: %s (%s)", detail, reason)
        return PollResult(
            status=ServiceStatus.UNKNOWN,
            status_detail=detail,
            poll_failure_reason=reason,
        )

    if not isinstance(incidents, list):
        return PollResult(status=ServiceStatus.OPERATIONAL, page_name="Trust Incidents")

    # Filter to active incidents (those without a resolved timestamp)
    active = [inc for inc in incidents if not inc.get("isResolved", True)]

    if not active:
        return PollResult(
            status=ServiceStatus.OPERATIONAL,
            page_name="Trust Incidents",
            incidents=[],
        )

    # Determine severity from active incidents
    severity = ServiceStatus.DEGRADED
    status_detail = None

    for inc in active:
        msg = inc.get("message", {})
        subject = msg.get("subject", "")
        severity_text = (msg.get("maintenanceType") or "").lower()

        if not status_detail:
            status_detail = subject

        if "major" in severity_text or "critical" in subject.lower():
            severity = ServiceStatus.MAJOR_OUTAGE
            status_detail = subject
            break
        if "disruption" in subject.lower() or "outage" in subject.lower():
            severity = ServiceStatus.PARTIAL_OUTAGE
            status_detail = subject

    return PollResult(
        status=severity,
        status_detail=status_detail,
        page_name="Trust Incidents",
        incidents=active,
    )
