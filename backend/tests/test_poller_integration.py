"""End-to-end poller tests using respx for httpx mocking.

These tests exercise each poller against realistic mocked responses
to confirm they produce the right PollResult shape for both happy paths
and failure modes (timeouts, 5xx, malformed JSON).
"""

import httpx
import pytest
import respx

from app.poller.active_incidents_poller import poll_active_incidents
from app.poller.current_status_poller import poll_current_status
from app.poller.normalizer import ServiceStatus
from app.poller.product_feed_poller import poll_product_feed
from app.poller.resilience import configure_breakers
from app.poller.service_array_poller import poll_service_array
from app.poller.statuspage_poller import poll_all_statuspage, poll_statuspage
from app.poller.trust_incidents_poller import poll_trust_incidents


@pytest.fixture(autouse=True)
def _reset_breakers():
    configure_breakers(threshold=3, ttl_seconds=0.2)


class TestStatuspagePoller:
    @respx.mock
    async def test_happy_path_operational(self):
        respx.get("https://status.example.com/api/v2/summary.json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "page": {"name": "Example Service"},
                    "status": {"indicator": "none", "description": "All Systems Operational"},
                    "components": [],
                    "incidents": [],
                    "scheduled_maintenances": [],
                },
            )
        )
        async with httpx.AsyncClient() as client:
            result = await poll_statuspage(client, "https://status.example.com/api/v2/summary.json")
        assert result.status == ServiceStatus.OPERATIONAL
        assert result.poll_failure_reason is None

    @respx.mock
    async def test_server_error_marks_unknown_with_reason(self):
        respx.get("https://dead.example.com/api/v2/summary.json").mock(
            return_value=httpx.Response(500)
        )
        async with httpx.AsyncClient() as client:
            result = await poll_statuspage(client, "https://dead.example.com/api/v2/summary.json")
        assert result.status == ServiceStatus.UNKNOWN
        assert result.poll_failure_reason is not None
        assert "500" in result.poll_failure_reason

    @respx.mock
    async def test_404_produces_http_failure_reason(self):
        respx.get("https://moved.example.com/api/v2/summary.json").mock(
            return_value=httpx.Response(404)
        )
        async with httpx.AsyncClient() as client:
            result = await poll_statuspage(client, "https://moved.example.com/api/v2/summary.json")
        assert result.status == ServiceStatus.UNKNOWN
        assert result.poll_failure_reason == "http_404"

    @respx.mock
    async def test_batch_polling_dedupes_urls(self):
        """Two services sharing one poll_url should cost one HTTP call."""
        route = respx.get("https://status.example.org/api/v2/summary.json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "page": {"name": "Example Org"},
                    "status": {"indicator": "none"},
                    "components": [
                        {"name": "Issue Tracker", "status": "operational", "description": None},
                        {
                            "name": "Wiki",
                            "status": "degraded_performance",
                            "description": "latency",
                        },
                    ],
                    "incidents": [],
                    "scheduled_maintenances": [],
                },
            )
        )
        services = [
            {
                "id": "issue-tracker",
                "poll_url": "https://status.example.org/api/v2/summary.json",
                "statuspage_component_name": "Issue Tracker",
            },
            {
                "id": "wiki",
                "poll_url": "https://status.example.org/api/v2/summary.json",
                "statuspage_component_name": "Wiki",
            },
        ]
        async with httpx.AsyncClient() as client:
            results = await poll_all_statuspage(client, services)
        assert route.call_count == 1
        result_map = dict(results)
        assert result_map["issue-tracker"].status == ServiceStatus.OPERATIONAL
        assert result_map["wiki"].status == ServiceStatus.DEGRADED


class TestCurrentStatusPoller:
    @respx.mock
    async def test_happy_path(self):
        respx.get("https://chat-status.example.com/api/v2.0.0/current").mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "ok",
                    "active_incidents": [],
                },
            )
        )
        async with httpx.AsyncClient() as client:
            result = await poll_current_status(
                client, "https://chat-status.example.com/api/v2.0.0/current"
            )
        assert result.status == ServiceStatus.OPERATIONAL

    @respx.mock
    async def test_list_response_no_active_is_operational(self):
        """Endpoint redirects /current to /history which returns a list of incident
        objects. An empty list or a list with only resolved/completed incidents
        means OPERATIONAL."""
        respx.get("https://chat-status.example.com/api/v2.0.0/current").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": 1, "status": "resolved", "type": "incident", "title": "old"},
                ],
            )
        )
        async with httpx.AsyncClient() as client:
            result = await poll_current_status(
                client, "https://chat-status.example.com/api/v2.0.0/current"
            )
        assert result.status == ServiceStatus.OPERATIONAL

    @respx.mock
    async def test_list_response_active_incident_maps_type(self):
        """Active incidents in the list response are mapped by `type`."""
        respx.get("https://chat-status.example.com/api/v2.0.0/current").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": 2, "status": "active", "type": "outage", "title": "Big one"},
                ],
            )
        )
        async with httpx.AsyncClient() as client:
            result = await poll_current_status(
                client, "https://chat-status.example.com/api/v2.0.0/current"
            )
        assert result.status == ServiceStatus.MAJOR_OUTAGE
        assert result.status_detail == "Big one"

    @respx.mock
    async def test_unexpected_type_returns_unknown(self):
        """Neither dict nor list (e.g., a bare string) still UNKNOWNs out."""
        respx.get("https://chat-status.example.com/api/v2.0.0/current").mock(
            return_value=httpx.Response(200, json="not-a-dict-or-list")
        )
        async with httpx.AsyncClient() as client:
            result = await poll_current_status(
                client, "https://chat-status.example.com/api/v2.0.0/current"
            )
        assert result.status == ServiceStatus.UNKNOWN


class TestTrustIncidentsPoller:
    @respx.mock
    async def test_no_active_incidents(self):
        respx.get("https://trust.example.com/v1/incidents").mock(
            return_value=httpx.Response(200, json=[])
        )
        async with httpx.AsyncClient() as client:
            result = await poll_trust_incidents(
                client,
                "https://trust.example.com/v1/incidents",
            )
        assert result.status == ServiceStatus.OPERATIONAL

    @respx.mock
    async def test_network_error(self):
        respx.get("https://trust.example.com/v1/incidents").mock(
            side_effect=httpx.ConnectError("DNS fail")
        )
        async with httpx.AsyncClient() as client:
            result = await poll_trust_incidents(
                client,
                "https://trust.example.com/v1/incidents",
            )
        assert result.status == ServiceStatus.UNKNOWN
        assert result.poll_failure_reason is not None
        assert "request_error" in result.poll_failure_reason


class TestActiveIncidentsPoller:
    @respx.mock
    async def test_happy_path(self):
        respx.get("https://support.example.com/api/incidents/active").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        async with httpx.AsyncClient() as client:
            result = await poll_active_incidents(
                client,
                "https://support.example.com/api/incidents/active",
            )
        assert result.status == ServiceStatus.OPERATIONAL


class TestServiceArrayPoller:
    @respx.mock
    async def test_all_good(self):
        respx.get("https://status.example.net/status.json").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"service": "Calling", "region": "US", "level": "Good", "alerts": []},
                ],
            )
        )
        async with httpx.AsyncClient() as client:
            result = await poll_service_array(
                client,
                "https://status.example.net/status.json",
            )
        assert result.status == ServiceStatus.OPERATIONAL


class TestProductFeedPoller:
    @respx.mock
    async def test_operational(self):
        respx.get("https://feed.example.com/incidents.json").mock(
            return_value=httpx.Response(200, json=[])
        )
        services = [{"id": "feed-product-a"}, {"id": "feed-product-b"}]
        async with httpx.AsyncClient() as client:
            results = await poll_product_feed(
                client,
                "https://feed.example.com/incidents.json",
                services,
            )
        assert len(results) == 2
        for _, r in results:
            assert r.status == ServiceStatus.OPERATIONAL

    @respx.mock
    async def test_error_propagates_to_each_service(self):
        respx.get("https://feed.example.com/incidents.json").mock(return_value=httpx.Response(500))
        services = [{"id": "feed-product-a"}, {"id": "feed-product-b"}]
        async with httpx.AsyncClient() as client:
            results = await poll_product_feed(
                client,
                "https://feed.example.com/incidents.json",
                services,
            )
        assert len(results) == 2
        for _, r in results:
            assert r.status == ServiceStatus.UNKNOWN
            assert r.poll_failure_reason is not None
