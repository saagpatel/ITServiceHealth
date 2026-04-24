"""Tests for GET /api/services/slo endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from app.alerting.burn_rate import BurnRateBreach
from app.config import settings
from app.database import close_db, init_db
from app.seed import load_dependencies, load_services
from app.sla import WindowUptime

# ---------------------------------------------------------------------------
# Fixtures (mirror test_admin_api.py pattern)
# ---------------------------------------------------------------------------

_CREATE_SVC = (
    "INSERT INTO services (id, display_name, category, tier, poll_type, current_status, poller_health) "
    "VALUES (?, ?, ?, ?, 'manual', ?, ?)"
)


async def _insert_service(
    conn: aiosqlite.Connection,
    *,
    service_id: str,
    display_name: str,
    category: str = "productivity",
    tier: str = "standard",
    current_status: str = "operational",
    poller_health: str = "healthy",
) -> None:
    await conn.execute(
        _CREATE_SVC,
        (service_id, display_name, category, tier, current_status, poller_health),
    )
    await conn.commit()


@pytest.fixture
async def seeded_app(tmp_path: Any) -> Any:
    """Provide a FastAPI app backed by a temp database seeded from services.yaml."""
    db_path = str(tmp_path / "test.db")
    conn = await init_db(db_path)

    services = load_services()
    from tests.test_seeder import seed_deps_with_db, seed_services_with_db

    await seed_services_with_db(conn, services)
    deps = load_dependencies(known_service_ids={s.id for s in services})
    await seed_deps_with_db(conn, deps, [s.id for s in services])

    from app.main import app

    yield app

    await close_db()


@pytest.fixture
async def client(seeded_app: Any) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=seeded_app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture
async def blank_app(tmp_path: Any) -> Any:
    """App with an empty database (no services seeded from YAML)."""
    db_path = str(tmp_path / "blank.db")
    await init_db(db_path)

    from app.main import app

    yield app

    await close_db()


@pytest.fixture
async def blank_client(blank_app: Any) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=blank_app),
        base_url="http://test",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSLOEndpoint:
    async def test_slo_endpoint_returns_all_services(self, client: Any) -> None:
        """Seeded services appear in data.services; each entry has required keys."""
        resp = await client.get("/api/services/slo")
        assert resp.status_code == 200
        body = resp.json()

        services = body["data"]["services"]
        assert isinstance(services, list)
        assert len(services) > 0

        required_keys = {
            "id",
            "display_name",
            "category",
            "tier",
            "current_status",
            "poller_health",
            "uptime_30d_pct",
            "error_budget_remaining_pct",
            "fast_burning",
            "slow_burning",
            "fast_breach",
            "slow_breach",
        }
        for svc in services:
            assert required_keys <= svc.keys(), f"Missing keys in service entry: {svc}"

    async def test_slo_includes_thresholds(self, client: Any) -> None:
        """data.thresholds matches settings defaults."""
        resp = await client.get("/api/services/slo")
        assert resp.status_code == 200
        thresholds = resp.json()["data"]["thresholds"]

        assert thresholds["target_percent"] == settings.slo_target_percent
        assert thresholds["fast_threshold"] == settings.slo_burn_rate_fast_threshold
        assert thresholds["slow_threshold"] == settings.slo_burn_rate_slow_threshold

    async def test_slo_response_envelope(self, client: Any) -> None:
        """Response matches {data, error, meta} envelope."""
        resp = await client.get("/api/services/slo")
        body = resp.json()
        assert "data" in body
        assert body["error"] is None
        assert body["meta"] is None

    async def test_slo_no_events_returns_full_budget(
        self, blank_client: Any, blank_app: Any, tmp_path: Any
    ) -> None:
        """Service with no status_events → budget=100.0, not burning."""
        from app.database import get_db

        db = await get_db()
        await db.execute(
            "INSERT INTO services (id, display_name, category, tier, poll_type, current_status, poller_health) "
            "VALUES ('svc_no_events', 'No Events Svc', 'identity', 'critical', 'manual', 'operational', 'healthy')"
        )
        await db.commit()

        resp = await blank_client.get("/api/services/slo")
        assert resp.status_code == 200

        services = resp.json()["data"]["services"]
        svc = next((s for s in services if s["id"] == "svc_no_events"), None)
        assert svc is not None, "svc_no_events not in response"

        assert svc["uptime_30d_pct"] is None
        assert svc["error_budget_remaining_pct"] == 100.0
        assert svc["fast_burning"] is False
        assert svc["slow_burning"] is False
        assert svc["fast_breach"] is None
        assert svc["slow_breach"] is None

    async def test_slo_flags_active_fast_breach(
        self, blank_client: Any, blank_app: Any, monkeypatch: Any
    ) -> None:
        """Monkeypatched evaluate_burn_rate returning a fast breach → fast_burning=True."""
        from app.database import get_db

        db = await get_db()
        await db.execute(
            "INSERT INTO services (id, display_name, category, tier, poll_type, current_status, poller_health) "
            "VALUES ('svc_breach', 'Breach Svc', 'productivity', 'standard', 'manual', 'degraded', 'healthy')"
        )
        await db.commit()

        fast_breach = BurnRateBreach(
            service_id="svc_breach",
            service_name="Breach Svc",
            severity="fast",
            long_window_burn_rate=20.0,
            short_window_burn_rate=22.5,
            error_budget_remaining_pct=60.0,
            long_window_label="1h",
            short_window_label="5m",
        )

        async def _fake_evaluate(
            _db: aiosqlite.Connection,
            service_id: str,
            service_name: str,
            _now: datetime,
        ) -> list[BurnRateBreach]:
            if service_id == "svc_breach":
                return [fast_breach]
            return []

        import app.router_services as rs_module

        monkeypatch.setattr(rs_module, "evaluate_burn_rate", _fake_evaluate)

        resp = await blank_client.get("/api/services/slo")
        assert resp.status_code == 200

        services = resp.json()["data"]["services"]
        svc = next((s for s in services if s["id"] == "svc_breach"), None)
        assert svc is not None

        assert svc["fast_burning"] is True
        assert svc["slow_burning"] is False

        fb = svc["fast_breach"]
        assert fb is not None
        assert fb["long_window_burn_rate"] == 20.0
        assert fb["short_window_burn_rate"] == 22.5
        assert fb["long_window_label"] == "1h"
        assert fb["short_window_label"] == "5m"
        assert svc["slow_breach"] is None

    async def test_slo_computes_budget_from_30d_uptime(
        self, blank_client: Any, blank_app: Any, monkeypatch: Any
    ) -> None:
        """99.95% 30d uptime → ~50% error budget remaining (SLO=99.9%, budget=0.1%)."""
        from app.database import get_db

        db = await get_db()
        await db.execute(
            "INSERT INTO services (id, display_name, category, tier, poll_type, current_status, poller_health) "
            "VALUES ('svc_budget', 'Budget Svc', 'productivity', 'standard', 'manual', 'operational', 'healthy')"
        )
        await db.commit()

        seconds_30d = 3600 * 24 * 30
        uptime_30d = WindowUptime(
            operational_seconds=seconds_30d * 0.9995,
            tracked_seconds=float(seconds_30d),
            uptime_percent=99.95,
        )

        import app.router_services as rs_module

        async def _fake_compute_uptime(
            _db: aiosqlite.Connection,
            _service_id: str,
            _window_start: datetime,
            _window_end: datetime,
        ) -> WindowUptime:
            return uptime_30d

        monkeypatch.setattr(rs_module, "compute_uptime", _fake_compute_uptime)

        resp = await blank_client.get("/api/services/slo")
        assert resp.status_code == 200

        services = resp.json()["data"]["services"]
        svc = next((s for s in services if s["id"] == "svc_budget"), None)
        assert svc is not None

        assert svc["uptime_30d_pct"] == 99.95
        # 99.9% SLO, budget=0.1%. Used=0.05% → 50% remaining.
        assert abs(svc["error_budget_remaining_pct"] - 50.0) < 1.0

    async def test_slo_includes_service_metadata(
        self, blank_client: Any, blank_app: Any
    ) -> None:
        """Service seeded with tier=critical, category=identity → response includes them."""
        from app.database import get_db

        db = await get_db()
        await db.execute(
            "INSERT INTO services (id, display_name, category, tier, poll_type, current_status, poller_health) "
            "VALUES ('svc_meta', 'Meta Svc', 'identity', 'critical', 'manual', 'operational', 'healthy')"
        )
        await db.commit()

        resp = await blank_client.get("/api/services/slo")
        assert resp.status_code == 200

        services = resp.json()["data"]["services"]
        svc = next((s for s in services if s["id"] == "svc_meta"), None)
        assert svc is not None
        assert svc["tier"] == "critical"
        assert svc["category"] == "identity"
        assert svc["display_name"] == "Meta Svc"
