"""Tests for the inbound Statuspage webhook receiver (Phase 7).

Scenarios:
  - Happy path: valid signature + known service → 200, row in status_events
  - Bad signature → 403
  - Disabled feature → 404
  - Unknown service_id → 404
  - Secret not configured → 503
  - Stale timestamp → 403
  - Unknown payload shape → 200, no crash
  - Unsubscribe ping → 200, no status change
"""

import hashlib
import hmac
import json
import time

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import close_db, init_db

SERVICE_ID = "wh-test-svc"
WEBHOOK_SECRET = "supersecretkey"
FAKE_URL = "https://status.wh-example.com/api/v2/summary.json"


# ── Signature helpers ──────────────────────────────────────────────────────────


def _sign_body(body: bytes, secret: str) -> str:
    """Compute the Statuspage-style HMAC-SHA256 hex signature."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _ts_header(offset_seconds: int = 0) -> str:
    """Return a Unix timestamp header value, offset from now."""
    return str(int(time.time()) + offset_seconds)


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def webhook_app(tmp_path, monkeypatch):
    """FastAPI app with webhooks enabled, backed by a real temp DB with one test service."""
    from pydantic import SecretStr

    db_path = str(tmp_path / "test.db")
    conn = await init_db(db_path)

    await conn.execute(
        """INSERT OR REPLACE INTO services
           (id, display_name, category, poll_type, poll_url,
            status_page_url, current_status, tier)
           VALUES (?, 'Webhook Test Service', 'other', 'statuspage_json', ?,
                   'https://status.wh-example.com', 'operational', 'important')""",
        (SERVICE_ID, FAKE_URL),
    )
    await conn.commit()

    monkeypatch.setattr(settings, "webhooks_enabled", True)
    monkeypatch.setattr(
        settings, "statuspage_webhook_secret", SecretStr(WEBHOOK_SECRET),
    )
    monkeypatch.setattr(settings, "slack_webhook_url", None)

    from app.main import app
    yield app, conn

    await close_db()


@pytest.fixture
async def webhook_client(webhook_app):
    """AsyncClient backed by the test app."""
    app, conn = webhook_app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, conn


# ── Helpers ────────────────────────────────────────────────────────────────────


def _build_headers(
    body: bytes,
    secret: str = WEBHOOK_SECRET,
    bad_sig: bool = False,
    omit_ts: bool = True,
    ts_offset: int = 0,
) -> dict[str, str]:
    sig = _sign_body(body, secret if not bad_sig else "wrongsecret")
    headers: dict[str, str] = {
        "X-Statuspage-Signature": sig,
        "Content-Type": "application/json",
    }
    if not omit_ts:
        headers["X-Statuspage-Timestamp"] = _ts_header(ts_offset)
    return headers


# ── Happy path ─────────────────────────────────────────────────────────────────


@respx.mock
async def test_valid_component_update_returns_200_and_writes_event(webhook_client):
    """A component_update webhook with a valid sig flips current_status and inserts an event."""
    client, conn = webhook_client
    # Slack is disabled via monkeypatch(slack_webhook_url=None), but stub anyway
    respx.post("https://hooks.slack.com/").mock(
        return_value=httpx.Response(200, text="ok"),
    )

    payload = {
        "meta": {"generated_at": "2026-04-22T12:00:00Z"},
        "page": {"id": "abc", "name": "Webhook Test"},
        "component_update": {
            "new_status": "major_outage",
            "old_status": "operational",
        },
    }
    body = json.dumps(payload).encode()
    resp = await client.post(
        f"/api/webhooks/statuspage/{SERVICE_ID}",
        content=body,
        headers=_build_headers(body),
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    cursor = await conn.execute(
        "SELECT previous_status, new_status, source FROM status_events WHERE service_id = ?",
        (SERVICE_ID,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row["previous_status"] == "operational"
    assert row["new_status"] == "major_outage"
    assert row["source"] == "webhook"

    cursor = await conn.execute(
        "SELECT current_status FROM services WHERE id = ?", (SERVICE_ID,),
    )
    svc = await cursor.fetchone()
    assert svc["current_status"] == "major_outage"


@respx.mock
async def test_valid_incident_update_returns_200_and_writes_event(webhook_client):
    """An incident-envelope webhook maps impact → ServiceStatus correctly."""
    client, conn = webhook_client
    respx.post("https://hooks.slack.com/").mock(
        return_value=httpx.Response(200, text="ok"),
    )

    payload = {
        "incident": {
            "id": "inc-001",
            "name": "API Performance Degraded",
            "status": "investigating",
            "impact": "minor",
        },
    }
    body = json.dumps(payload).encode()
    resp = await client.post(
        f"/api/webhooks/statuspage/{SERVICE_ID}",
        content=body,
        headers=_build_headers(body),
    )

    assert resp.status_code == 200

    cursor = await conn.execute(
        "SELECT new_status FROM status_events WHERE service_id = ?", (SERVICE_ID,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row["new_status"] == "degraded"


# ── Rejection paths ────────────────────────────────────────────────────────────


async def test_bad_signature_returns_403(webhook_client):
    client, _ = webhook_client
    payload = {"component_update": {"new_status": "major_outage", "old_status": "operational"}}
    body = json.dumps(payload).encode()
    resp = await client.post(
        f"/api/webhooks/statuspage/{SERVICE_ID}",
        content=body,
        headers=_build_headers(body, bad_sig=True),
    )
    assert resp.status_code == 403


async def test_disabled_returns_404(tmp_path, monkeypatch):
    """When webhooks_enabled=False the endpoint returns 404."""
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    monkeypatch.setattr(settings, "webhooks_enabled", False)

    from app.main import app

    payload = {"component_update": {"new_status": "major_outage"}}
    body = json.dumps(payload).encode()
    sig = _sign_body(body, WEBHOOK_SECRET)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.post(
            f"/api/webhooks/statuspage/{SERVICE_ID}",
            content=body,
            headers={"X-Statuspage-Signature": sig, "Content-Type": "application/json"},
        )
    assert resp.status_code == 404
    await close_db()


async def test_unknown_service_returns_404(webhook_client):
    client, _ = webhook_client
    payload = {"component_update": {"new_status": "major_outage", "old_status": "operational"}}
    body = json.dumps(payload).encode()
    resp = await client.post(
        "/api/webhooks/statuspage/nonexistent-service",
        content=body,
        headers=_build_headers(body),
    )
    assert resp.status_code == 404


async def test_secret_not_configured_returns_503(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    monkeypatch.setattr(settings, "webhooks_enabled", True)
    monkeypatch.setattr(settings, "statuspage_webhook_secret", None)

    from app.main import app

    body = b'{"component_update": {"new_status": "degraded"}}'
    sig = _sign_body(body, WEBHOOK_SECRET)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.post(
            f"/api/webhooks/statuspage/{SERVICE_ID}",
            content=body,
            headers={"X-Statuspage-Signature": sig, "Content-Type": "application/json"},
        )
    assert resp.status_code == 503
    await close_db()


async def test_stale_timestamp_returns_403(webhook_client):
    """A timestamp older than 5 minutes should be rejected."""
    client, _ = webhook_client
    payload = {"component_update": {"new_status": "major_outage", "old_status": "operational"}}
    body = json.dumps(payload).encode()
    resp = await client.post(
        f"/api/webhooks/statuspage/{SERVICE_ID}",
        content=body,
        headers=_build_headers(body, omit_ts=False, ts_offset=-400),
    )
    assert resp.status_code == 403


@respx.mock
async def test_fresh_timestamp_accepted(webhook_client):
    """A fresh timestamp header should not cause rejection."""
    client, _ = webhook_client
    respx.post("https://hooks.slack.com/").mock(
        return_value=httpx.Response(200, text="ok"),
    )
    payload = {"component_update": {"new_status": "degraded", "old_status": "operational"}}
    body = json.dumps(payload).encode()
    resp = await client.post(
        f"/api/webhooks/statuspage/{SERVICE_ID}",
        content=body,
        headers=_build_headers(body, omit_ts=False, ts_offset=0),
    )
    assert resp.status_code == 200


# ── Unknown / unusual payloads ────────────────────────────────────────────────


async def test_unknown_payload_shape_returns_200_no_crash(webhook_client):
    """A payload that doesn't contain component_update or incident should 200 gracefully."""
    client, _ = webhook_client
    payload = {"some_future_field": {"data": "whatever"}}
    body = json.dumps(payload).encode()
    resp = await client.post(
        f"/api/webhooks/statuspage/{SERVICE_ID}",
        content=body,
        headers=_build_headers(body),
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_no_status_change_when_same_status(webhook_client):
    """A webhook reporting the same status as current should produce no status_event."""
    client, conn = webhook_client
    payload = {
        "component_update": {
            "new_status": "operational",
            "old_status": "operational",
        },
    }
    body = json.dumps(payload).encode()
    resp = await client.post(
        f"/api/webhooks/statuspage/{SERVICE_ID}",
        content=body,
        headers=_build_headers(body),
    )
    assert resp.status_code == 200

    cursor = await conn.execute(
        "SELECT count(*) FROM status_events WHERE service_id = ?", (SERVICE_ID,),
    )
    count = (await cursor.fetchone())[0]
    assert count == 0


async def test_unsubscribe_ping_returns_200(webhook_client):
    """Statuspage unsubscribe confirmation should 200 without touching the DB."""
    client, _ = webhook_client
    payload = {
        "meta": {"unsubscribe": True, "documentation": "https://help.statuspage.io"},
    }
    body = json.dumps(payload).encode()
    resp = await client.post(
        f"/api/webhooks/statuspage/{SERVICE_ID}",
        content=body,
        headers=_build_headers(body),
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
