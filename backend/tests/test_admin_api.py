"""Tests for the admin API endpoint: POST /api/admin/status."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import close_db, init_db
from app.seed import load_dependencies, load_services, seed_dependencies, seed_services

ADMIN_TOKEN = "test-admin-token-xyz"
AUTH_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture(autouse=True)
def _set_admin_token(monkeypatch):
    """Provision an admin token for every test in this module."""
    monkeypatch.setattr(settings, "admin_api_token", ADMIN_TOKEN)


@pytest.fixture
async def seeded_app(tmp_path):
    """Provide a FastAPI app with a seeded temp database."""
    db_path = str(tmp_path / "test.db")
    conn = await init_db(db_path)

    services = load_services()
    from tests.test_seeder import seed_deps_with_db, seed_services_with_db
    await seed_services_with_db(conn, services)
    deps = load_dependencies(known_service_ids={s.id for s in services})
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


class TestAdminAuth:
    async def test_missing_token_rejected(self, client):
        resp = await client.post("/api/admin/status", json={
            "service_id": "okta",
            "new_status": "degraded",
            "reason": "test",
        })
        assert resp.status_code == 401

    async def test_wrong_token_rejected(self, client):
        resp = await client.post(
            "/api/admin/status",
            json={
                "service_id": "okta",
                "new_status": "degraded",
                "reason": "test",
            },
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 403

    async def test_unset_token_returns_503(self, client, monkeypatch):
        monkeypatch.setattr(settings, "admin_api_token", None)
        resp = await client.post(
            "/api/admin/status",
            json={
                "service_id": "okta",
                "new_status": "degraded",
                "reason": "test",
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 503

    async def test_non_bearer_scheme_rejected(self, client):
        resp = await client.post(
            "/api/admin/status",
            json={
                "service_id": "okta",
                "new_status": "degraded",
                "reason": "test",
            },
            headers={"Authorization": f"Basic {ADMIN_TOKEN}"},
        )
        assert resp.status_code == 401


class TestAdminStatusEndpoint:
    async def test_update_valid_service(self, client):
        resp = await client.post(
            "/api/admin/status",
            json={
                "service_id": "okta",
                "new_status": "degraded",
                "detail": "SSO slow",
                "reason": "User reported in #it-help",
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["current_status"] == "degraded"
        assert body["data"]["current_status_detail"] == "SSO slow"
        assert body["meta"]["status_changed"] is True
        assert body["meta"]["previous_status"] == "unknown"
        assert body["error"] is None

    async def test_update_nonexistent_service(self, client):
        resp = await client.post(
            "/api/admin/status",
            json={
                "service_id": "nonexistent",
                "new_status": "degraded",
                "reason": "test",
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_update_invalid_status(self, client):
        resp = await client.post(
            "/api/admin/status",
            json={
                "service_id": "okta",
                "new_status": "invalid_status",
                "reason": "test",
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    async def test_update_missing_reason(self, client):
        resp = await client.post(
            "/api/admin/status",
            json={
                "service_id": "okta",
                "new_status": "degraded",
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    async def test_update_creates_status_event_with_audit(self, client):
        resp = await client.post(
            "/api/admin/status",
            json={
                "service_id": "workday",
                "new_status": "major_outage",
                "detail": "Down",
                "reason": "Confirmed with vendor support",
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200

        from app.database import get_db
        db = await get_db()
        cursor = await db.execute(
            """SELECT source, new_status, updated_by, reason, client_ip
               FROM status_events WHERE service_id='workday'"""
        )
        row = dict(await cursor.fetchone())
        assert row["source"] == "manual"
        assert row["new_status"] == "major_outage"
        assert row["updated_by"] == "admin"
        assert row["reason"] == "Confirmed with vendor support"
        # client_ip is populated when request.client is available
        # (ASGITransport sets it to None, which is acceptable)

    async def test_update_same_status_no_event(self, client):
        await client.post(
            "/api/admin/status",
            json={
                "service_id": "concur",
                "new_status": "degraded",
                "reason": "first update",
            },
            headers=AUTH_HEADERS,
        )
        resp = await client.post(
            "/api/admin/status",
            json={
                "service_id": "concur",
                "new_status": "degraded",
                "detail": "Still slow",
                "reason": "follow-up",
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["status_changed"] is False

        from app.database import get_db
        db = await get_db()
        cursor = await db.execute(
            "SELECT count(*) FROM status_events WHERE service_id='concur'"
        )
        assert (await cursor.fetchone())[0] == 1

    async def test_response_envelope_structure(self, client):
        resp = await client.post(
            "/api/admin/status",
            json={
                "service_id": "okta",
                "new_status": "operational",
                "reason": "resolved",
            },
            headers=AUTH_HEADERS,
        )
        body = resp.json()
        assert "data" in body
        assert "error" in body
        assert "meta" in body
