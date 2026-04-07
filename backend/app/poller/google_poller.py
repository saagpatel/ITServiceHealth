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
        response = await client.get(poll_url)
        response.raise_for_status()
        incidents = response.json()
    except httpx.HTTPStatusError as e:
        logger.warning("HTTP %d from Google status: %s", e.response.status_code, e)
        return [
            (svc["id"], PollResult(status=ServiceStatus.UNKNOWN, status_detail=f"HTTP {e.response.status_code}"))
            for svc in services
        ]
    except httpx.RequestError as e:
        logger.warning("Request error polling Google status: %s", e)
        return [
            (svc["id"], PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e)))
            for svc in services
        ]
    except Exception as e:
        logger.warning("Unexpected error polling Google status: %s", e)
        return [
            (svc["id"], PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e)))
            for svc in services
        ]

    if not isinstance(incidents, list):
        logger.warning("Google incidents.json returned non-list: %s", type(incidents))
        incidents = []

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
