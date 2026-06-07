"""Tests for the poller resilience layer (stamina retries + purgatory breakers)."""

import asyncio

import httpx
import pytest
import respx

from app.poller.resilience import (
    CircuitBreakerOpen,
    TransientHTTPError,
    configure_breakers,
    describe_fetch_error,
    host_of,
    resilient_fetch,
)


@pytest.fixture(autouse=True)
def _fast_and_isolated_breakers():
    """Rebuild breakers with a tight threshold + TTL for test speed, fresh per test."""
    configure_breakers(threshold=2, ttl_seconds=0.5)
    yield
    configure_breakers(threshold=2, ttl_seconds=0.5)


class TestHostOf:
    def test_extracts_host(self):
        assert host_of("https://status.example.com/api/v2/summary.json") == "status.example.com"

    def test_bare_url_fallback(self):
        assert host_of("not-a-url") == "not-a-url"


class TestResilientFetch:
    @respx.mock
    async def test_success_first_try(self):
        respx.get("https://example.com/ok").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with httpx.AsyncClient() as client:
            resp = await resilient_fetch(client, "https://example.com/ok")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}

    @respx.mock
    async def test_retries_transient_5xx_then_succeeds(self):
        route = respx.get("https://example.com/flaky").mock(
            side_effect=[
                httpx.Response(502),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        async with httpx.AsyncClient() as client:
            resp = await resilient_fetch(
                client,
                "https://example.com/flaky",
                attempts=3,
                timeout=5.0,
            )
            assert resp.status_code == 200
            assert route.call_count == 2

    @respx.mock
    async def test_retries_429(self):
        route = respx.get("https://example.com/ratelimited").mock(
            side_effect=[
                httpx.Response(429),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        async with httpx.AsyncClient() as client:
            resp = await resilient_fetch(
                client,
                "https://example.com/ratelimited",
                attempts=3,
                timeout=5.0,
            )
            assert resp.status_code == 200
            assert route.call_count == 2

    @respx.mock
    async def test_does_not_retry_404(self):
        route = respx.get("https://example.com/missing").mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await resilient_fetch(
                    client,
                    "https://example.com/missing",
                    attempts=3,
                    timeout=5.0,
                )
            # 404 is a hard failure — no retries
            assert route.call_count == 1

    @respx.mock
    async def test_all_retries_exhausted_raises_transient(self):
        respx.get("https://example.com/dead").mock(return_value=httpx.Response(503))
        async with httpx.AsyncClient() as client:
            with pytest.raises(TransientHTTPError):
                await resilient_fetch(
                    client,
                    "https://example.com/dead",
                    attempts=2,
                    timeout=5.0,
                )

    @respx.mock
    async def test_breaker_opens_after_threshold(self):
        """Two consecutive hard failures trip the breaker for this host.
        Subsequent calls raise CircuitBreakerOpen without hitting the network."""
        route = respx.get("https://trip.example.com/x").mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            # First attempt: exhausts retries, counts as 1 failure
            with pytest.raises(TransientHTTPError):
                await resilient_fetch(
                    client,
                    "https://trip.example.com/x",
                    attempts=1,
                    timeout=5.0,
                )
            # Second attempt: also fails, tripping the threshold-2 breaker
            with pytest.raises(TransientHTTPError):
                await resilient_fetch(
                    client,
                    "https://trip.example.com/x",
                    attempts=1,
                    timeout=5.0,
                )
            # Third attempt: breaker is open, fast-fails without hitting network
            calls_before = route.call_count
            with pytest.raises(CircuitBreakerOpen):
                await resilient_fetch(
                    client,
                    "https://trip.example.com/x",
                    attempts=1,
                    timeout=5.0,
                )
            assert route.call_count == calls_before  # no new network call

    @respx.mock
    async def test_breaker_isolates_hosts(self):
        """One host's breaker must not affect another host."""
        respx.get("https://bad.example.com/x").mock(return_value=httpx.Response(500))
        respx.get("https://good.example.com/x").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        async with httpx.AsyncClient() as client:
            # Trip the bad host
            for _ in range(2):
                with pytest.raises(TransientHTTPError):
                    await resilient_fetch(
                        client,
                        "https://bad.example.com/x",
                        attempts=1,
                        timeout=5.0,
                    )
            # Good host should still succeed cleanly
            resp = await resilient_fetch(
                client,
                "https://good.example.com/x",
                attempts=1,
                timeout=5.0,
            )
            assert resp.status_code == 200

    @respx.mock
    async def test_breaker_recovers_after_ttl(self):
        """Open breaker should half-open after TTL and allow probe."""
        route = respx.get("https://heal.example.com/x").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(500),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        async with httpx.AsyncClient() as client:
            # Trip the breaker with threshold=2
            for _ in range(2):
                with pytest.raises(TransientHTTPError):
                    await resilient_fetch(
                        client,
                        "https://heal.example.com/x",
                        attempts=1,
                        timeout=5.0,
                    )
            with pytest.raises(CircuitBreakerOpen):
                await resilient_fetch(
                    client,
                    "https://heal.example.com/x",
                    attempts=1,
                    timeout=5.0,
                )

            # Wait for TTL to elapse, then probe succeeds
            await asyncio.sleep(0.6)
            resp = await resilient_fetch(
                client,
                "https://heal.example.com/x",
                attempts=1,
                timeout=5.0,
            )
            assert resp.status_code == 200
            assert route.call_count == 3


class TestDescribeFetchError:
    def test_breaker_open(self):
        detail, reason = describe_fetch_error(
            CircuitBreakerOpen("Circuit breaker open for host 'x.example.com'")
        )
        assert "suspended" in detail.lower()
        assert reason.startswith("circuit_breaker_open")

    def test_timeout(self):
        detail, reason = describe_fetch_error(TimeoutError())
        assert detail == "Poll timeout"
        assert reason == "timeout"

    def test_transient_http(self):
        detail, reason = describe_fetch_error(TransientHTTPError(503, "https://example.com"))
        assert detail == "HTTP 503"
        assert reason == "transient_http_503"

    def test_hard_http_error(self):
        req = httpx.Request("GET", "https://example.com/x")
        resp = httpx.Response(404, request=req)
        err = httpx.HTTPStatusError("not found", request=req, response=resp)
        detail, reason = describe_fetch_error(err)
        assert detail == "HTTP 404"
        assert reason == "http_404"

    def test_request_error(self):
        err = httpx.ConnectError("DNS fail")
        detail, reason = describe_fetch_error(err)
        assert "DNS fail" in detail
        assert reason == "request_error: ConnectError"

    def test_unexpected(self):
        detail, reason = describe_fetch_error(ValueError("boom"))
        assert detail == "boom"
        assert reason == "unexpected: ValueError"
