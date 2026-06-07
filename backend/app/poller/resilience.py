"""Resilient HTTP fetch for pollers: retries + per-host circuit breaker.

Wraps every outbound vendor request with:

  1. Retry (stamina) — exponential backoff + jitter on transient errors
     (network errors, timeouts, 408/429/5xx). Capped at `attempts` tries
     and `timeout` seconds wall-clock.
  2. Circuit breaker (purgatory) — one breaker per vendor host. After
     `breaker_threshold` consecutive failures the breaker opens and
     subsequent calls fast-fail with `CircuitBreakerOpen` for
     `breaker_ttl_seconds` before probing again.

Philosophy: transient errors should self-heal quickly (stamina). A
persistently-dead host shouldn't consume our poll cycle (purgatory).
HTTP 4xx errors other than 408/429 are treated as hard failures —
they won't fix themselves with retries and usually indicate a config
issue (URL moved, auth change), so they surface immediately.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import httpx
import stamina
from purgatory import AsyncCircuitBreakerFactory
from purgatory.domain.model import OpenedState

from app.observability.metrics import record_circuit_breaker_state

logger = logging.getLogger(__name__)

# HTTP status codes that indicate a transient server-side problem worth retrying.
# Everything else (including 4xx non-408/429) is a hard failure from our POV.
TRANSIENT_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})

DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_TIMEOUT = 30.0
DEFAULT_RETRY_WAIT_INITIAL = 0.5
DEFAULT_RETRY_WAIT_MAX = 5.0
DEFAULT_RETRY_WAIT_JITTER = 1.0

# Circuit-breaker defaults. Status pages recover slowly — a 5-minute TTL
# avoids the classic "constantly re-probe a dead host" antipattern.
DEFAULT_BREAKER_THRESHOLD = 3
DEFAULT_BREAKER_TTL_SECONDS = 300.0


class CircuitBreakerOpen(Exception):
    """Raised when a host's breaker has tripped. Callers should surface
    this as a distinct poller-health signal, not a vendor outage."""


class TransientHTTPError(httpx.HTTPError):
    """Internal marker for HTTP status codes we want to retry.

    Inherits from httpx.HTTPError so callers can catch a single base type
    when they don't care about the distinction.
    """

    def __init__(self, status_code: int, url: str):
        super().__init__(f"Transient HTTP {status_code} from {url}")
        self.status_code = status_code
        self.url = url


_breaker_factory: AsyncCircuitBreakerFactory | None = None
_breaker_threshold: int = DEFAULT_BREAKER_THRESHOLD
_breaker_ttl: float = DEFAULT_BREAKER_TTL_SECONDS


def _on_breaker_event(name: str, event_type: str, event) -> None:
    """Mirror purgatory state transitions into the Prometheus gauge.

    purgatory dispatches events as (name, event_type, event). We only
    care about `state_changed` events — the others carry redundant info.
    State values are 'opened', 'closed', 'half-opened'; normalize the
    hyphen to underscore to match the label registered in metrics.py.
    """
    if event_type != "state_changed":
        return
    state_label = getattr(event, "state", "closed").replace("-", "_")
    record_circuit_breaker_state(name, state_label)


def configure_breakers(
    threshold: int = DEFAULT_BREAKER_THRESHOLD,
    ttl_seconds: float = DEFAULT_BREAKER_TTL_SECONDS,
) -> None:
    """Rebuild the factory with new defaults. Call once at app startup.

    Tests also call this (via reset_breakers) to get a clean slate between
    cases so one test's failures don't leave another test's breaker open.
    """
    global _breaker_factory, _breaker_threshold, _breaker_ttl
    _breaker_threshold = threshold
    _breaker_ttl = ttl_seconds
    _breaker_factory = AsyncCircuitBreakerFactory(
        default_threshold=threshold,
        default_ttl=ttl_seconds,
    )
    # Subscribe to state-change events so metrics stay in sync with reality
    _breaker_factory.add_listener(_on_breaker_event)


def reset_breakers() -> None:
    """Discard all breaker state. Intended for test isolation."""
    configure_breakers(_breaker_threshold, _breaker_ttl)


def _get_factory() -> AsyncCircuitBreakerFactory:
    if _breaker_factory is None:
        configure_breakers()
    assert _breaker_factory is not None
    return _breaker_factory


def host_of(url: str) -> str:
    """Extract hostname for breaker keying. Falls back to the full URL if
    parsing fails so we never key on an empty string."""
    parsed = urlparse(url)
    return parsed.hostname or url


async def resilient_fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    attempts: int = DEFAULT_RETRY_ATTEMPTS,
    timeout: float = DEFAULT_RETRY_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET `url` with retries and a per-host circuit breaker.

    `headers` forwards through to ``client.get`` so pollers that need
    vendor-specific headers (e.g., ``Accept: application/json`` for
    some vendors' redirect-happy status hosts) can pass them without
    bypassing the resilience layer.

    Raises:
        CircuitBreakerOpen: host's breaker is tripped; caller should treat
            this as poller-unhealthy, not vendor-down.
        httpx.HTTPStatusError: non-transient HTTP error (e.g., 404, 401).
            Not retried.
        httpx.RequestError / TransientHTTPError: all retries exhausted.
    """
    host = host_of(url)
    factory = _get_factory()
    breaker = await factory.get_breaker(host)

    @stamina.retry(
        on=(httpx.RequestError, httpx.TimeoutException, TransientHTTPError),
        attempts=attempts,
        timeout=timeout,
        wait_initial=DEFAULT_RETRY_WAIT_INITIAL,
        wait_max=DEFAULT_RETRY_WAIT_MAX,
        wait_jitter=DEFAULT_RETRY_WAIT_JITTER,
    )
    async def _do_fetch() -> httpx.Response:
        response = await client.get(url, headers=headers)
        if response.status_code in TRANSIENT_HTTP_CODES:
            raise TransientHTTPError(response.status_code, url)
        response.raise_for_status()
        return response

    try:
        async with breaker:
            return await _do_fetch()
    except OpenedState as e:
        # Breaker is open — log at DEBUG because we expect repeated skips
        # while the TTL runs out; the initial open is logged separately.
        logger.debug("Breaker open for %s (%s)", host, e)
        raise CircuitBreakerOpen(f"Circuit breaker open for host '{host}'") from e


def describe_fetch_error(error: BaseException) -> tuple[str, str]:
    """Return (user-facing detail, mechanical failure reason) for a fetch error.

    Keeps the UI-facing `status_detail` short and shareable, while the
    `poll_failure_reason` keeps the full diagnostic context for operators.
    Used by every poller so failure strings stay consistent across the DB.
    """
    if isinstance(error, CircuitBreakerOpen):
        return (
            "Poller temporarily suspended (host unreachable)",
            f"circuit_breaker_open: {error}",
        )
    if isinstance(error, asyncio.TimeoutError):
        return ("Poll timeout", "timeout")
    if isinstance(error, TransientHTTPError):
        return (
            f"HTTP {error.status_code}",
            f"transient_http_{error.status_code}",
        )
    if isinstance(error, httpx.HTTPStatusError):
        return (
            f"HTTP {error.response.status_code}",
            f"http_{error.response.status_code}",
        )
    if isinstance(error, httpx.RequestError):
        return (
            str(error) or type(error).__name__,
            f"request_error: {type(error).__name__}",
        )
    return (str(error) or type(error).__name__, f"unexpected: {type(error).__name__}")
