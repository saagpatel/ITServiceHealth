"""Tests for the Phase 3 observability layer.

Covers:
  - metrics helpers (outcome_from_failure_reason, record_* helpers)
  - sentry_setup secret scrubbing
  - heartbeat dead-man's switch (fresh / stale / gauge-refresh)
  - /metrics and /healthz endpoints
"""

import time

import pytest

from app.observability import heartbeat
from app.observability.metrics import (
    BREAKER_STATE_VALUE,
    POLLER_HEALTH_VALUE,
    STATUS_VALUE,
    outcome_from_failure_reason,
    record_circuit_breaker_state,
    record_poller_health,
    record_service_status,
    CIRCUIT_BREAKER_STATE,
    POLLER_HEALTH_STATE,
    SCHEDULER_LAST_HEARTBEAT_SECONDS,
    SERVICE_STATUS,
)
from app.observability.sentry_setup import _scrub


class TestOutcomeFromFailureReason:
    def test_none_is_ok(self):
        assert outcome_from_failure_reason(None) == "ok"

    def test_breaker_open(self):
        assert outcome_from_failure_reason("circuit_breaker_open: x") == "circuit_open"

    def test_timeout(self):
        assert outcome_from_failure_reason("timeout") == "timeout"

    def test_http_5xx(self):
        assert outcome_from_failure_reason("http_503") == "http_5xx"
        assert outcome_from_failure_reason("transient_http_502") == "http_5xx"

    def test_http_4xx(self):
        assert outcome_from_failure_reason("http_404") == "http_4xx"
        assert outcome_from_failure_reason("transient_http_429") == "http_4xx"

    def test_request_error(self):
        assert outcome_from_failure_reason("request_error: ConnectError") == "request_error"

    def test_parse_error(self):
        assert outcome_from_failure_reason("parse_error: expected dict") == "parse_error"

    def test_other(self):
        assert outcome_from_failure_reason("unexpected: ValueError") == "other"


class TestMetricRecorders:
    def test_record_service_status_sets_gauge(self):
        record_service_status("test-svc", "major_outage")
        value = SERVICE_STATUS.labels(service="test-svc")._value.get()
        assert value == STATUS_VALUE["major_outage"]

    def test_unknown_status_maps_to_unknown_value(self):
        record_service_status("test-svc2", "bogus_status")
        value = SERVICE_STATUS.labels(service="test-svc2")._value.get()
        assert value == STATUS_VALUE["unknown"]

    def test_record_poller_health(self):
        record_poller_health("poller-svc", "broken")
        value = POLLER_HEALTH_STATE.labels(service="poller-svc")._value.get()
        assert value == POLLER_HEALTH_VALUE["broken"]

    def test_record_circuit_breaker_state(self):
        record_circuit_breaker_state("example.com", "opened")
        value = CIRCUIT_BREAKER_STATE.labels(host="example.com")._value.get()
        assert value == BREAKER_STATE_VALUE["opened"]


class TestSentryScrubbing:
    def test_redacts_slack_webhook(self):
        body = "posting to https://hooks.slack.com/services/T123/B456/xyzxyz"
        assert "xyzxyz" not in _scrub(body)
        assert "[REDACTED]" in _scrub(body)

    def test_redacts_bearer_token(self):
        headers = {"authorization": "Bearer abc.def.ghi"}
        out = _scrub(headers)
        assert "abc.def.ghi" not in str(out)

    def test_deep_nested_structures_scrubbed(self):
        event = {
            "request": {
                "headers": {"Authorization": "Bearer secret-token-here"},
            },
            "extra": {
                "breadcrumbs": ["fetched https://hooks.slack.com/services/X/Y/secret"],
            },
        }
        out = _scrub(event)
        assert "secret-token-here" not in str(out)
        assert "secret" not in str(out["extra"])

    def test_non_string_values_untouched(self):
        assert _scrub(42) == 42
        assert _scrub(None) is None
        assert _scrub([1, 2, 3]) == [1, 2, 3]


class TestHeartbeat:
    def setup_method(self):
        heartbeat._last_heartbeat_monotonic = time.monotonic()

    def test_fresh_after_tick(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "heartbeat_stale_after_seconds", 120)
        heartbeat._mark_heartbeat()
        assert heartbeat.is_heartbeat_fresh()
        assert heartbeat.get_seconds_since_heartbeat() < 1.0

    def test_stale_when_past_threshold(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "heartbeat_stale_after_seconds", 1)
        # Backdate by faking the monotonic value
        heartbeat._last_heartbeat_monotonic = time.monotonic() - 10
        assert not heartbeat.is_heartbeat_fresh()
        assert heartbeat.get_seconds_since_heartbeat() >= 10

    def test_gauge_update_reports_age(self):
        heartbeat._last_heartbeat_monotonic = time.monotonic() - 3
        heartbeat.update_heartbeat_gauge_continuously()
        reported = SCHEDULER_LAST_HEARTBEAT_SECONDS._value.get()
        assert reported >= 3.0

    async def test_tick_without_ping_url(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "healthcheck_ping_url", None)
        # Should not raise even without a configured ping URL
        await heartbeat.heartbeat_tick()
        assert heartbeat.is_heartbeat_fresh()

    async def test_tick_swallows_ping_failure(self, monkeypatch):
        # Set a bogus URL — the ping will fail, but the tick must not raise
        from app.config import settings
        monkeypatch.setattr(
            settings, "healthcheck_ping_url",
            "http://127.0.0.1:1/definitely-not-listening",
        )
        await heartbeat.heartbeat_tick()
        # Heartbeat still marked despite the ping failure
        assert heartbeat.is_heartbeat_fresh()


class TestObservabilityEndpoints:
    @pytest.fixture
    async def app_client(self, tmp_path):
        """Provide a real app + httpx client with a temp DB."""
        from httpx import ASGITransport, AsyncClient
        from app.database import close_db, init_db

        await init_db(str(tmp_path / "test.db"))
        from app.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c
        await close_db()

    async def test_metrics_endpoint_returns_prometheus_text(self, app_client):
        resp = await app_client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        body = resp.text
        # At least one of our metrics should be registered
        assert "poll_total" in body or "scheduler_last_heartbeat_seconds" in body

    async def test_healthz_fresh_returns_200(self, app_client, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "heartbeat_stale_after_seconds", 120)
        heartbeat._last_heartbeat_monotonic = time.monotonic()
        resp = await app_client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["heartbeat_age_seconds"] < 5

    async def test_healthz_stale_returns_503(self, app_client, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "heartbeat_stale_after_seconds", 1)
        heartbeat._last_heartbeat_monotonic = time.monotonic() - 60
        resp = await app_client.get("/healthz")
        assert resp.status_code == 503
        assert resp.json()["status"] == "stale"
