"""Google Workspace status poller.

Fetches the incidents.json feed from Google's status dashboard.
One HTTP call serves both Google Mail and Google Calendar.
"""

import logging

import httpx

from app.poller.normalizer import (
    GOOGLE_PRODUCT_NAMES,
    ServiceStatus,
    normalize_google_status,
)
from app.poller.resilience import describe_fetch_error, resilient_fetch
from app.poller.statuspage_poller import PollResult

logger = logging.getLogger(__name__)


async def poll_google(
    client: httpx.AsyncClient,
    poll_url: str,
    services: list[dict],
) -> list[tuple[str, PollResult]]:
    """Poll Google Workspace status for multiple products in one call.

    Args:
        client: Shared httpx AsyncClient.
        poll_url: Google incidents.json URL.
        services: DB rows with key 'id' (e.g., "google-mail", "google-calendar").

    Returns:
        List of (service_id, PollResult) tuples.
    """
    try:
        response = await resilient_fetch(client, poll_url)
        incidents = response.json()
    except Exception as e:
        detail, reason = describe_fetch_error(e)
        logger.warning("Google poll failed: %s (%s)", detail, reason)
        return [
            (svc["id"], PollResult(
                status=ServiceStatus.UNKNOWN,
                status_detail=detail,
                poll_failure_reason=reason,
            ))
            for svc in services
        ]

    if not isinstance(incidents, list):
        logger.warning("Google incidents.json returned non-list: %s", type(incidents))
        return [
            (svc["id"], PollResult(
                status=ServiceStatus.UNKNOWN,
                status_detail="Unexpected response format",
                poll_failure_reason=f"parse_error: expected list, got {type(incidents).__name__}",
            ))
            for svc in services
        ]

    results: list[tuple[str, PollResult]] = []
    for svc in services:
        service_id = svc["id"]
        status = normalize_google_status(incidents, service_id)

        # Find status detail from most recent active incident for this product
        status_detail = None
        product_names = GOOGLE_PRODUCT_NAMES.get(service_id, [])
        for incident in incidents:
            if incident.get("end"):
                continue
            affected = incident.get("affected_products", [])
            if any(p.get("title") in product_names for p in affected):
                status_detail = incident.get("external_desc", "")[:200]
                break

        results.append((
            service_id,
            PollResult(
                status=status,
                status_detail=status_detail,
                page_name="Google Workspace",
                incidents=[
                    inc for inc in incidents
                    if not inc.get("end") and any(
                        p.get("title") in product_names
                        for p in inc.get("affected_products", [])
                    )
                ],
                scheduled_maintenances=[],
            ),
        ))

    return results
