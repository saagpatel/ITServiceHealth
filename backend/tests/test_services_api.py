"""Tests for GET /api/services and GET /api/services/{id} — shape assertions.

Specifically verifies that the three pending-status fields added in the
flapping-badge feature are present in both the list and detail responses.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import close_db, init_db
from app.seed import load_dependencies, load_services


@pytest.fixture
async def seeded_app(tmp_path):
    """FastAPI app backed by a temp database seeded with real services."""
    db_path = str(tmp_path / "test.db")
    conn = await init_db(db_path)

    from tests.test_seeder import (
        _DEPENDENCIES_YAML,
        _SERVICES_YAML,
        seed_deps_with_db,
        seed_services_with_db,
    )

    services = load_services(path=_SERVICES_YAML)
    await seed_services_with_db(conn, services)
    deps = load_dependencies(path=_DEPENDENCIES_YAML, known_service_ids={s.id for s in services})
    await seed_deps_with_db(conn, deps, [s.id for s in services])

    from app.main import app

    yield app

    await close_db()


@pytest.fixture
async def client(seeded_app):
    async with AsyncClient(
        transport=ASGITransport(app=seeded_app),
        base_url="http://test",
    ) as c:
        yield c


class TestServicesListShape:
    async def test_list_services_returns_200(self, client):
        resp = await client.get("/api/services")
        assert resp.status_code == 200

    async def test_list_services_includes_pending_status_fields(self, client):
        resp = await client.get("/api/services")
        body = resp.json()
        services = body["data"]["services"]
        assert len(services) > 0

        first = services[0]
        # All three pending-status fields must be present (value may be None).
        assert "pending_status" in first
        assert "pending_status_count" in first
        assert "pending_status_since" in first

    async def test_list_services_category_filter_includes_pending_fields(self, client):
        resp = await client.get("/api/services?category=identity")
        body = resp.json()
        services = body["data"]["services"]
        assert len(services) > 0

        for svc in services:
            assert "pending_status" in svc
            assert "pending_status_count" in svc
            assert "pending_status_since" in svc

    async def test_list_services_pending_status_null_by_default(self, client):
        """Freshly-seeded services have no pending state — fields should be null."""
        resp = await client.get("/api/services")
        body = resp.json()
        for svc in body["data"]["services"]:
            assert svc["pending_status"] is None
            assert svc["pending_status_since"] is None


class TestServiceDetailShape:
    async def test_detail_includes_pending_status_fields(self, client):
        resp = await client.get("/api/services/identity-provider")
        assert resp.status_code == 200
        body = resp.json()
        svc = body["data"]["service"]

        assert "pending_status" in svc
        assert "pending_status_count" in svc
        assert "pending_status_since" in svc

    async def test_detail_nonexistent_returns_404(self, client):
        resp = await client.get("/api/services/nonexistent-xyz")
        assert resp.status_code == 404
