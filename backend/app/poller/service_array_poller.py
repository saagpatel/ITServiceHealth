"""Service-array status poller.

Fetches status from an endpoint that returns an array of per-service
status objects, each carrying a level field and optional alerts list.
Overall status is derived from the worst level across all entries.
"""

import logging

import httpx

from app.poller.normalizer import ServiceStatus
from app.poller.resilience import describe_fetch_error, resilient_fetch
from app.poller.statuspage_poller import PollResult

logger = logging.getLogger(__name__)

# Level field values → our status
LEVEL_MAP = {
    "Good": ServiceStatus.OPERATIONAL,
    "Informational": ServiceStatus.OPERATIONAL,
    "Minor": ServiceStatus.DEGRADED,
    "Major": ServiceStatus.PARTIAL_OUTAGE,
    "Critical": ServiceStatus.MAJOR_OUTAGE,
}


async def poll_service_array(
    client: httpx.AsyncClient,
    poll_url: str,
) -> PollResult:
    """Poll a service-array status endpoint.

    The endpoint returns an array of objects like:
    { "category": "Core Services", "service": "Calling - Inbound",
      "region": "Americas", "level": "Good", "alerts": [] }

    Overall status is computed from the worst level across all entries.
    """
    try:
        response = await resilient_fetch(client, poll_url)
        services = response.json()
    except Exception as e:
        detail, reason = describe_fetch_error(e)
        logger.warning("Service-array poll failed: %s (%s)", detail, reason)
        return PollResult(
            status=ServiceStatus.UNKNOWN,
            status_detail=detail,
            poll_failure_reason=reason,
        )

    if not isinstance(services, list):
        return PollResult(status=ServiceStatus.OPERATIONAL, page_name="Service Array")

    # Compute worst status across all services
    worst = ServiceStatus.OPERATIONAL
    worst_detail = None
    active_alerts = []

    severity_rank = {
        ServiceStatus.OPERATIONAL: 0,
        ServiceStatus.DEGRADED: 1,
        ServiceStatus.PARTIAL_OUTAGE: 2,
        ServiceStatus.MAJOR_OUTAGE: 3,
        ServiceStatus.UNKNOWN: -1,
    }

    for svc in services:
        level = svc.get("level", "Good")
        status = LEVEL_MAP.get(level, ServiceStatus.UNKNOWN)
        alerts = svc.get("alerts", [])

        if alerts:
            active_alerts.extend(alerts)

        if severity_rank.get(status, 0) > severity_rank.get(worst, 0):
            worst = status
            worst_detail = f"{svc.get('service', '')} ({svc.get('region', '')}): {level}"

    return PollResult(
        status=worst,
        status_detail=worst_detail if worst != ServiceStatus.OPERATIONAL else None,
        page_name="Service Array",
        incidents=active_alerts,
    )
