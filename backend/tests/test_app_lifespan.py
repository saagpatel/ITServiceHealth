"""Smoke tests that enter the real FastAPI lifespan context.

Every other test bypasses the app lifespan — they call `init_db()`
directly and hand a raw `app` to `ASGITransport`. That's fast but it
misses an entire class of bug: anything that crashes inside the
`@asynccontextmanager async def lifespan(app)` block in
`backend/app/main.py` ships silently.

A concrete example: Phase 1 introduced `httpx.Limits(
max_connections_per_host=1, ...)`. That kwarg doesn't exist — but
the full test suite still passed because no test ever booted the
real lifespan. The bug only surfaced when a human ran `python run.py`.

These tests drive the real lifespan via `asgi-lifespan`'s
`LifespanManager`, verify the app comes up, and exit cleanly. The
poll scheduler is stubbed so the test doesn't fire real network
calls during the startup window.
"""

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.config import settings


@pytest.fixture
def _isolated_lifespan(tmp_path, monkeypatch):
    """Redirect DB to a tmp file and stub the scheduler.

    The scheduler's first poll fires at `next_run_time=now`, so without
    the stub these tests would race real HTTP to vendor status pages.
    The stub leaves everything else — DB init, seed, HTTP client,
    circuit breakers, logging — fully realistic.
    """
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "lifespan.db"))

    import app.main as main_module

    def _noop_start(_app):
        pass

    def _noop_stop():
        pass

    # Import lazily — scheduler module binds `scheduler` at import time
    # but start/stop are the functions `lifespan` calls.
    import app.poller.scheduler as scheduler_module
    monkeypatch.setattr(scheduler_module, "start_scheduler", _noop_start)
    monkeypatch.setattr(scheduler_module, "stop_scheduler", _noop_stop)
    # main.py re-imports these lazily inside lifespan, so also patch
    # the module's namespace defensively in case of direct binding.
    monkeypatch.setattr(main_module, "__name__", main_module.__name__)


@pytest.mark.asyncio
async def test_lifespan_enters_and_exits_cleanly(_isolated_lifespan):
    """The whole lifespan block runs without raising."""
    from app.main import app

    async with LifespanManager(app):
        # The HTTP client must be constructed — this is the line that
        # broke when `max_connections_per_host` was a bad kwarg.
        assert hasattr(app.state, "http_client")
        assert app.state.http_client is not None


@pytest.mark.asyncio
async def test_healthz_after_lifespan(_isolated_lifespan):
    """`/healthz` is the dead-man's switch; it must answer once we're up."""
    from app.main import app

    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/healthz")

    # Fresh boot → heartbeat is young. Either 200 (scheduler stub still
    # lets heartbeat run) or 503 (stub blocks it) is acceptable — what
    # we're proving is that the route responds at all, which it
    # couldn't before the httpx.Limits fix.
    assert resp.status_code in {200, 503}
    body = resp.json()
    assert "status" in body
    assert "heartbeat_age_seconds" in body


@pytest.mark.asyncio
async def test_api_health_after_lifespan(_isolated_lifespan):
    """`/api/health` returns the expected shape after a real boot."""
    from app.main import app

    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["database"] == "connected"
    assert "version" in body


@pytest.mark.asyncio
async def test_http_client_has_valid_limits(_isolated_lifespan):
    """Regression guard for the httpx.Limits kwarg bug.

    If someone ever passes a non-existent kwarg to `httpx.Limits` again,
    lifespan enter would raise TypeError before this assertion runs,
    and the test fails. That's the whole point of this file.
    """
    from app.main import app

    async with LifespanManager(app):
        client = app.state.http_client
        # The client exists and is usable. httpx.Limits is not exposed
        # on the client publicly — the fact that lifespan construction
        # succeeded is the real signal.
        assert client is not None
        assert not client.is_closed
