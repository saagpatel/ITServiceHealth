"""Statuspage.io JSON API poller.

Fetches /api/v2/summary.json from any Statuspage.io-powered status page
and returns normalized status data. Supports both single-service and
batch polling with URL deduplication.
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field

import httpx

from app.poller.normalizer import (
    ServiceStatus,
    normalize_statuspage_component,
    normalize_statuspage_indicator,
)

logger = logging.getLogger(__name__)


@dataclass
class PollResult:
    """Result from polling a single service's status page."""

    status: ServiceStatus
    status_detail: str | None = None
    page_name: str | None = None
    incidents: list[dict] = field(default_factory=list)
    scheduled_maintenances: list[dict] = field(default_factory=list)


async def fetch_statuspage_json(client: httpx.AsyncClient, url: str) -> dict:
    """Fetch a Statuspage.io summary.json URL and return parsed JSON.

    Raises on HTTP error or parse failure — caller handles exceptions.
    """
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


def extract_service_status(
    data: dict,
    component_name: str | None = None,
) -> PollResult:
    """Extract service status from an already-fetched Statuspage.io JSON response.

    Pure function — no I/O. Checks for a matching component first, falls back
    to page-level indicator if no component match.
    """
    page_name = data.get("page", {}).get("name")
    status = ServiceStatus.UNKNOWN
    status_detail = None

    if component_name:
        for comp in data.get("components", []):
            if comp.get("name", "").lower() == component_name.lower():
                status = normalize_statuspage_component(comp.get("status", ""))
                status_detail = comp.get("description")
                break

    # Fall back to page-level indicator
    if status == ServiceStatus.UNKNOWN:
        indicator = data.get("status", {}).get("indicator", "")
        status = normalize_statuspage_indicator(indicator)
        status_detail = data.get("status", {}).get("description")

    return PollResult(
        status=status,
        status_detail=status_detail,
        page_name=page_name,
        incidents=data.get("incidents", []),
        scheduled_maintenances=data.get("scheduled_maintenances", []),
    )


async def poll_statuspage(
    client: httpx.AsyncClient,
    poll_url: str,
    component_name: str | None = None,
) -> PollResult:
    """Poll a single Statuspage.io summary.json endpoint.

    Convenience wrapper: fetches JSON then extracts status.
    """
    try:
        data = await fetch_statuspage_json(client, poll_url)
    except httpx.HTTPStatusError as e:
        logger.warning("HTTP %d from %s: %s", e.response.status_code, poll_url, e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=f"HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        logger.warning("Request error polling %s: %s", poll_url, e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e))
    except Exception as e:
        logger.warning("Unexpected error polling %s: %s", poll_url, e)
        return PollResult(status=ServiceStatus.UNKNOWN, status_detail=str(e))

    return extract_service_status(data, component_name)


async def poll_all_statuspage(
    client: httpx.AsyncClient,
    services: list[dict],
) -> list[tuple[str, PollResult]]:
    """Batch-poll all statuspage_json services with URL deduplication.

    Groups services by poll_url (e.g., 3 Atlassian services share one URL),
    fetches each unique URL once, then fans out results to individual services.

    Args:
        services: DB rows with keys: id, poll_url, statuspage_component_name

    Returns:
        List of (service_id, PollResult) tuples.
    """
    # Group services by poll_url for deduplication
    url_to_services: dict[str, list[dict]] = defaultdict(list)
    for svc in services:
        url_to_services[svc["poll_url"]].append(svc)

    # Fetch each unique URL concurrently
    urls = list(url_to_services.keys())

    async def _fetch_with_timeout(url: str) -> tuple[str, dict | Exception]:
        try:
            data = await asyncio.wait_for(
                fetch_statuspage_json(client, url),
                timeout=10.0,
            )
            return (url, data)
        except Exception as e:
            return (url, e)

    fetched = await asyncio.gather(
        *[_fetch_with_timeout(url) for url in urls],
    )

    # Fan out results to individual services
    results: list[tuple[str, PollResult]] = []
    for url, data_or_error in fetched:
        svcs = url_to_services[url]

        if isinstance(data_or_error, Exception):
            error = data_or_error
            detail = str(error)
            if isinstance(error, asyncio.TimeoutError):
                detail = "Poll timeout (10s)"
            logger.warning("Failed to fetch %s: %s", url, detail)
            for svc in svcs:
                results.append((
                    svc["id"],
                    PollResult(status=ServiceStatus.UNKNOWN, status_detail=detail),
                ))
        else:
            data = data_or_error
            for svc in svcs:
                result = extract_service_status(data, svc.get("statuspage_component_name"))
                results.append((svc["id"], result))

    return results


async def _demo_poll() -> None:
    """Demo: poll Box status page and print results."""
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
    ) as client:
        result = await poll_statuspage(
            client,
            "https://status.box.com/api/v2/summary.json",
        )
        print(f"Page: {result.page_name}")
        print(f"Status: {result.status.value}")
        print(f"Detail: {result.status_detail}")
        print(f"Active incidents: {len(result.incidents)}")
        print(f"Scheduled maintenances: {len(result.scheduled_maintenances)}")

        if result.incidents:
            for inc in result.incidents:
                print(f"  Incident: {inc.get('name')} ({inc.get('status')})")

        if result.scheduled_maintenances:
            for m in result.scheduled_maintenances:
                print(f"  Maintenance: {m.get('name')} ({m.get('scheduled_for')})")


if __name__ == "__main__":
    import asyncio as _asyncio
    _asyncio.run(_demo_poll())
