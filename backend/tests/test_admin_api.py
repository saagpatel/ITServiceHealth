"""Tests for the admin API endpoint: POST /api/admin/status."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import close_db, init_db
from app.seed import load_dependencies, load_services, seed_dependencies, seed_services


@pytest.fixture
async def seeded_app(tmp_path):
    """Provide a FastAPI app with a seeded temp database."""
    db_path = str(tmp_path / "test.db")
    import app.database as db_module
    conn = await init_db(db_path)

    services = load_services()
    from tests.test_seeder import seed_services_with_db, seed_deps_with_db
    await seed_services_with_db(conn, services)
    deps = load_dependencies()
    await seed_deps_with_db(conn, deps, [s.id for s in services])

    # Import app after DB is initialized
    from app.main import app
    yield app

    await close_db()


@pytest.fixture
async def client(seeded_app):
    """Provide an httpx AsyncClient for the test app."""
    async with AsyncClient(
        transport=ASGITransport(app=seeded_app),
        base_url="http://test",
    ) as c:
        yield c


class TestAdminStatusEndpoint:
    async def test_update_valid_service(self, client):
        resp = await client.post("/api/admin/status", json={
            "service_id": "okta",
            "new_status": "degraded",
            "detail": "SSO slow",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["current_status"] == "degraded"
        assert body["data"]["current_status_detail"] == "SSO slow"
        assert body["meta"]["status_changed"] is True
        assert body["meta"]["previous_status"] == "unknown"
        assert body["error"] is None

    async def test_update_nonexistent_service(self, client):
        resp = await client.post("/api/admin/status", json={
            "service_id": "nonexistent",
            "new_status": "degraded",
        })
        assert resp.status_code == 404

    async def test_update_invalid_status(self, client):
        resp = await client.post("/api/admin/status", json={
            "service_id": "okta",
            "new_status": "invalid_status",
        })
        assert resp.status_code == 422

    async def test_update_creates_status_event(self, client):
        # First update to create a change
        await client.post("/api/admin/status", json={
            "service_id": "workday",
            "new_status": "major_outage",
            "detail": "Down",
        })

        # Check DB directly
        from app.database import get_db
        db = await get_db()
        cursor = await db.execute(
            "SELECT source, new_status FROM status_events WHERE service_id='workday'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert dict(row)["source"] == "manual"
        assert dict(row)["new_status"] == "major_outage"

    async def test_update_same_status_no_event(self, client):
        # Set to degraded
        await client.post("/api/admin/status", json={
            "service_id": "concur",
            "new_status": "degraded",
        })
        # Set to degraded again
        resp = await client.post("/api/admin/status", json={
            "service_id": "concur",
            "new_status": "degraded",
            "detail": "Still slow",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["status_changed"] is False

        # Should only have 1 event (from first change), not 2
        from app.database import get_db
        db = await get_db()
        cursor = await db.execute(
            "SELECT count(*) FROM status_events WHERE service_id='concur'"
        )
        assert (await cursor.fetchone())[0] == 1

    async def test_response_envelope_structure(self, client):
        resp = await client.post("/api/admin/status", json={
            "service_id": "okta",
            "new_status": "operational",
        })
        body = resp.json()
        assert "data" in body
        assert "error" in body
        assert "meta" in body
