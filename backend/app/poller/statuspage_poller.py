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
from app.poller.resilience import (
    CircuitBreakerOpen,
    describe_fetch_error,
    resilient_fetch,
)

logger = logging.getLogger(__name__)


@dataclass
class PollResult:
    """Result from polling a single service's status page.

    `status_detail` carries user-facing vendor text when the poll succeeded
    (e.g., "Investigating API latency") and a short error summary when it
    didn't (e.g., "HTTP 502"). `poll_failure_reason` carries the mechanical
    reason for a failed poll so the change detector can record it against
    the service's poller-health trail separately from the status_detail the
    UI shows. It is None when the poll succeeded.
    """

    status: ServiceStatus
    status_detail: str | None = None
    page_name: str | None = None
    incidents: list[dict] = field(default_factory=list)
    scheduled_maintenances: list[dict] = field(default_factory=list)
    poll_failure_reason: str | None = None


async def fetch_statuspage_json(client: httpx.AsyncClient, url: str) -> dict:
    """Fetch a Statuspage.io summary.json URL and return parsed JSON.

    Uses resilient_fetch under the hood: retries transient errors with
    backoff, opens a per-host circuit breaker after repeated failures.
    Raises on HTTP error, breaker open, or parse failure — caller handles.
    """
    response = await resilient_fetch(client, url)
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

    Convenience wrapper: fetches JSON then extracts status. Never raises —
    on failure returns UNKNOWN with a poll_failure_reason that the change
    detector records against the service's poller-health trail.
    """
    try:
        data = await fetch_statuspage_json(client, poll_url)
    except Exception as e:
        detail, reason = describe_fetch_error(e)
        logger.warning("Poll failed for %s: %s (%s)", poll_url, detail, reason)
        return PollResult(
            status=ServiceStatus.UNKNOWN,
            status_detail=detail,
            poll_failure_reason=reason,
        )

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

    async def _fetch_one(url: str) -> tuple[str, dict | Exception]:
        """Fetch with resilience. Returns (url, data|exception)."""
        try:
            data = await fetch_statuspage_json(client, url)
            return (url, data)
        except Exception as e:
            return (url, e)

    fetched = await asyncio.gather(*[_fetch_one(url) for url in urls])

    # Fan out results to individual services
    results: list[tuple[str, PollResult]] = []
    for url, data_or_error in fetched:
        svcs = url_to_services[url]

        if isinstance(data_or_error, Exception):
            detail, reason = describe_fetch_error(data_or_error)
            logger.warning("Failed to fetch %s: %s (%s)", url, detail, reason)
            for svc in svcs:
                results.append((
                    svc["id"],
                    PollResult(
                        status=ServiceStatus.UNKNOWN,
                        status_detail=detail,
                        poll_failure_reason=reason,
                    ),
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
