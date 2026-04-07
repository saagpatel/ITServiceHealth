"""Salesforce Trust API poller.

Fetches active incidents from api.status.salesforce.com/v1/incidents
and maps to our status model.
"""

import logging

import httpx

from app.poller.normalizer import ServiceStatus
from app.poller.statuspage_poller import PollResult

logger = logging.getLogger(__name__)


async def poll_salesforce(
    client: httpx.AsyncClient,
    poll_url: str,
) -> PollResult:
    """Poll the Salesforce Trust API for active incidents.

    The API returns a list of incident objects. If any are active
    (no resolvedAt), the service is degraded/outaged.
    """
    try:
        response = await client.get(poll_url)
        response.raise_for_status()
        incidents = response.json()
    except httpx.HTTPStatusError as e:
        logger.warning("HTTP %d from Salesforce Trust API: %s", e.response.status_code, e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=f"HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        logger.warning("Request error polling Salesforce Trust API: %s", e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e))
    except Exception as e:
        logger.warning("Unexpected error polling Salesforce Trust API: %s", e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e))

    if not isinstance(incidents, list):
        return PollResult(status=ServiceStatus.OPERATIONAL, page_name="Salesforce")

    # Filter to active incidents (those without a resolved timestamp)
    active = []
    for inc in incidents:
        instance_keys = inc.get("instanceKeys", [])
        is_resolved = inc.get("isResolved", True)
        if not is_resolved:
            active.append(inc)

    if not active:
        return PollResult(
            status=ServiceStatus.OPERATIONAL,
            page_name="Salesforce",
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
        page_name="Salesforce",
        incidents=active,
    )
