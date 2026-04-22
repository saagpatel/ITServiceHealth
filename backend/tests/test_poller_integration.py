"""End-to-end poller tests using respx for httpx mocking.

These tests exercise each vendor poller against realistic mocked responses
to confirm they produce the right PollResult shape for both happy paths
and failure modes (timeouts, 5xx, malformed JSON).
"""

import httpx
import pytest
import respx

from app.poller.google_poller import poll_google
from app.poller.normalizer import ServiceStatus
from app.poller.resilience import configure_breakers
from app.poller.ringcentral_poller import poll_ringcentral
from app.poller.salesforce_poller import poll_salesforce
from app.poller.slack_poller import poll_slack
from app.poller.statuspage_poller import poll_all_statuspage, poll_statuspage
from app.poller.zendesk_poller import poll_zendesk


@pytest.fixture(autouse=True)
def _reset_breakers():
    configure_breakers(threshold=3, ttl_seconds=0.2)


class TestStatuspagePoller:
    @respx.mock
    async def test_happy_path_operational(self):
        respx.get("https://status.box.com/api/v2/summary.json").mock(
            return_value=httpx.Response(200, json={
                "page": {"name": "Box"},
                "status": {"indicator": "none", "description": "All Systems Operational"},
                "components": [],
                "incidents": [],
                "scheduled_maintenances": [],
            })
        )
        async with httpx.AsyncClient() as client:
            result = await poll_statuspage(client, "https://status.box.com/api/v2/summary.json")
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
        route = respx.get("https://status.atlassian.com/api/v2/summary.json").mock(
            return_value=httpx.Response(200, json={
                "page": {"name": "Atlassian"},
                "status": {"indicator": "none"},
                "components": [
                    {"name": "Jira", "status": "operational", "description": None},
                    {"name": "Confluence", "status": "degraded_performance", "description": "latency"},
                ],
                "incidents": [],
                "scheduled_maintenances": [],
            })
        )
        services = [
            {
                "id": "jira",
                "poll_url": "https://status.atlassian.com/api/v2/summary.json",
                "statuspage_component_name": "Jira",
            },
            {
                "id": "confluence",
                "poll_url": "https://status.atlassian.com/api/v2/summary.json",
                "statuspage_component_name": "Confluence",
            },
        ]
        async with httpx.AsyncClient() as client:
            results = await poll_all_statuspage(client, services)
        assert route.call_count == 1
        result_map = dict(results)
        assert result_map["jira"].status == ServiceStatus.OPERATIONAL
        assert result_map["confluence"].status == ServiceStatus.DEGRADED


class TestSlackPoller:
    @respx.mock
    async def test_happy_path(self):
        respx.get("https://slack-status.com/api/v2.0.0/current").mock(
            return_value=httpx.Response(200, json={
                "status": "ok",
                "active_incidents": [],
            })
        )
        async with httpx.AsyncClient() as client:
            result = await poll_slack(client, "https://slack-status.com/api/v2.0.0/current")
        assert result.status == ServiceStatus.OPERATIONAL

    @respx.mock
    async def test_non_dict_response(self):
        respx.get("https://slack-status.com/api/v2.0.0/current").mock(
            return_value=httpx.Response(200, json=["unexpected"])
        )
        async with httpx.AsyncClient() as client:
            result = await poll_slack(client, "https://slack-status.com/api/v2.0.0/current")
        assert result.status == ServiceStatus.UNKNOWN
        assert result.poll_failure_reason is not None
        assert "parse_error" in result.poll_failure_reason


class TestSalesforcePoller:
    @respx.mock
    async def test_no_active_incidents(self):
        respx.get("https://api.status.salesforce.com/v1/incidents").mock(
            return_value=httpx.Response(200, json=[])
        )
        async with httpx.AsyncClient() as client:
            result = await poll_salesforce(
                client, "https://api.status.salesforce.com/v1/incidents",
            )
        assert result.status == ServiceStatus.OPERATIONAL

    @respx.mock
    async def test_network_error(self):
        respx.get("https://api.status.salesforce.com/v1/incidents").mock(
            side_effect=httpx.ConnectError("DNS fail")
        )
        async with httpx.AsyncClient() as client:
            result = await poll_salesforce(
                client, "https://api.status.salesforce.com/v1/incidents",
            )
        assert result.status == ServiceStatus.UNKNOWN
        assert result.poll_failure_reason is not None
        assert "request_error" in result.poll_failure_reason


class TestZendeskPoller:
    @respx.mock
    async def test_happy_path(self):
        respx.get("https://status.zendesk.com/api/incidents/active").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        async with httpx.AsyncClient() as client:
            result = await poll_zendesk(
                client, "https://status.zendesk.com/api/incidents/active",
            )
        assert result.status == ServiceStatus.OPERATIONAL


class TestRingCentralPoller:
    @respx.mock
    async def test_all_good(self):
        respx.get("https://status.ringcentral.com/status.json").mock(
            return_value=httpx.Response(200, json=[
                {"service": "Calling", "region": "US", "level": "Good", "alerts": []},
            ])
        )
        async with httpx.AsyncClient() as client:
            result = await poll_ringcentral(
                client, "https://status.ringcentral.com/status.json",
            )
        assert result.status == ServiceStatus.OPERATIONAL


class TestGooglePoller:
    @respx.mock
    async def test_operational(self):
        respx.get("https://www.google.com/appsstatus/incidents.json").mock(
            return_value=httpx.Response(200, json=[])
        )
        services = [{"id": "google-mail"}, {"id": "google-calendar"}]
        async with httpx.AsyncClient() as client:
            results = await poll_google(
                client, "https://www.google.com/appsstatus/incidents.json", services,
            )
        assert len(results) == 2
        for _, r in results:
            assert r.status == ServiceStatus.OPERATIONAL

    @respx.mock
    async def test_error_propagates_to_each_service(self):
        respx.get("https://www.google.com/appsstatus/incidents.json").mock(
            return_value=httpx.Response(500)
        )
        services = [{"id": "google-mail"}, {"id": "google-calendar"}]
        async with httpx.AsyncClient() as client:
            results = await poll_google(
                client, "https://www.google.com/appsstatus/incidents.json", services,
            )
        assert len(results) == 2
        for _, r in results:
            assert r.status == ServiceStatus.UNKNOWN
            assert r.poll_failure_reason is not None
