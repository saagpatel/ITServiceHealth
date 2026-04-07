"""RingCentral Status API poller.

Fetches service status from status.ringcentral.com/status.json
which returns an array of 75 service status objects.
"""

import logging

import httpx

from app.poller.normalizer import ServiceStatus
from app.poller.statuspage_poller import PollResult

logger = logging.getLogger(__name__)

# RingCentral level values → our status
LEVEL_MAP = {
    "Good": ServiceStatus.OPERATIONAL,
    "Informational": ServiceStatus.OPERATIONAL,
    "Minor": ServiceStatus.DEGRADED,
    "Major": ServiceStatus.PARTIAL_OUTAGE,
    "Critical": ServiceStatus.MAJOR_OUTAGE,
}


async def poll_ringcentral(
    client: httpx.AsyncClient,
    poll_url: str,
) -> PollResult:
    """Poll RingCentral status API.

    Returns an array of objects like:
    { "category": "Core Services", "service": "Calling - Inbound",
      "region": "Americas", "level": "Good", "alerts": [] }

    We compute overall status from the worst level across all services.
    """
    try:
        response = await client.get(poll_url)
        response.raise_for_status()
        services = response.json()
    except httpx.HTTPStatusError as e:
        logger.warning("HTTP %d from RingCentral status: %s", e.response.status_code, e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=f"HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        logger.warning("Request error polling RingCentral status: %s", e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e))
    except Exception as e:
        logger.warning("Unexpected error polling RingCentral status: %s", e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e))

    if not isinstance(services, list):
        return PollResult(status=ServiceStatus.OPERATIONAL, page_name="RingCentral")

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
        page_name="RingCentral",
        incidents=active_alerts,
    )
