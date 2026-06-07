"""Tests for the Slack slash command endpoint — /api/slack/slash.

Scenarios:
  1.  Missing signature header → 401
  2.  Bad signature → 401
  3.  Stale timestamp → 401
  4.  Feature disabled (slack_slash_enabled=False) → 503
  5.  Signing secret unset → 503
  6.  Exact id match → 200, correct service block
  7.  Case-insensitive display_name match → 200, correct service block
  8.  Unique substring match → 200, correct service block
  9.  Ambiguous substring match → 200, disambiguation text
  10. No match → 200, "No service matches" text
  11. Empty text → 200, "Usage:" hint
  12. Poller broken → "Unknown" shown even when status is operational
  13. Wrong command name → 200, "Unknown slash command" text
"""

import hashlib
import hmac
import time
import urllib.parse

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.config import settings
from app.database import close_db, init_db

SIGNING_SECRET = "slash_test_signing_secret_xyz"


# ── Signature helpers (mirrors test_slack_ack.py) ─────────────────────────────


def _slack_sign(body: bytes, secret: str, ts: str) -> str:
    """Compute a Slack v0 signature."""
    base = f"v0:{ts}:{body.decode()}"
    digest = hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return f"v0={digest}"


def _ts_now(offset: int = 0) -> str:
    return str(int(time.time()) + offset)


def _form_body_for_slash(params: dict) -> bytes:
    """Encode slash-command parameters as flat x-www-form-urlencoded bytes.

    Slash commands POST flat key/value pairs, NOT wrapped in a `payload=` field
    like the interactivity endpoint.
    """
    return urllib.parse.urlencode(params).encode()


def _headers(
    body: bytes,
    secret: str = SIGNING_SECRET,
    bad_sig: bool = False,
    ts_offset: int = 0,
) -> dict[str, str]:
    ts = _ts_now(ts_offset)
    sig = _slack_sign(body, secret if not bad_sig else "badsecret", ts)
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
    }


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def slash_app(tmp_path, monkeypatch):
    """FastAPI app with slash command enabled, backed by a real temp DB seeded
    with a small set of services for matching tests."""
    db_path = str(tmp_path / "test.db")
    conn = await init_db(db_path)

    services = [
        (
            "identity-provider",
            "Identity Provider",
            "identity",
            "critical",
            "operational",
            "healthy",
        ),
        (
            "video-conferencing",
            "Video Conferencing",
            "collaboration",
            "important",
            "degraded",
            "healthy",
        ),
        ("ticketing", "Ticketing", "itsm", "important", "operational", "healthy"),
        ("chat-platform", "Chat Platform", "collaboration", "critical", "operational", "healthy"),
        ("chat-bot", "Chat Bot", "collaboration", "important", "operational", "healthy"),
        ("broken_svc", "Broken Service", "other", "low", "operational", "broken"),
    ]

    for svc_id, name, cat, tier, status, health in services:
        await conn.execute(
            """INSERT OR REPLACE INTO services
               (id, display_name, category, poll_type, poll_url,
                current_status, tier, poller_health, last_status_change_at)
               VALUES (?, ?, ?, 'statuspage_json', 'https://example.com/x',
                       ?, ?, ?, '2026-04-24T00:00:00Z')""",
            (svc_id, name, cat, status, tier, health),
        )
    await conn.commit()

    monkeypatch.setattr(settings, "slack_slash_enabled", True)
    monkeypatch.setattr(settings, "slack_signing_secret", SecretStr(SIGNING_SECRET))

    from app.main import app

    yield app, conn

    await close_db()


@pytest.fixture
async def slash_client(slash_app):
    """AsyncClient backed by the slash test app."""
    app, conn = slash_app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, conn


# ── 1. Missing signature header → 401 ────────────────────────────────────────


async def test_missing_signature_header(slash_client):
    client, _ = slash_client
    body = _form_body_for_slash({"command": "/itstatus", "text": "identity-provider"})
    ts = _ts_now()
    resp = await client.post(
        "/api/slack/slash",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            # X-Slack-Signature deliberately omitted
        },
    )
    assert resp.status_code == 401


# ── 2. Bad signature → 401 ────────────────────────────────────────────────────


async def test_bad_signature(slash_client):
    client, _ = slash_client
    body = _form_body_for_slash({"command": "/itstatus", "text": "identity-provider"})
    resp = await client.post(
        "/api/slack/slash",
        content=body,
        headers=_headers(body, bad_sig=True),
    )
    assert resp.status_code == 401


# ── 3. Stale timestamp → 401 ─────────────────────────────────────────────────


async def test_stale_timestamp(slash_client):
    client, _ = slash_client
    body = _form_body_for_slash({"command": "/itstatus", "text": "identity-provider"})
    resp = await client.post(
        "/api/slack/slash",
        content=body,
        headers=_headers(body, ts_offset=-600),  # 10 minutes old
    )
    assert resp.status_code == 401


# ── 4. Feature disabled → 503 ────────────────────────────────────────────────


async def test_feature_disabled(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    monkeypatch.setattr(settings, "slack_slash_enabled", False)
    monkeypatch.setattr(settings, "slack_signing_secret", SecretStr(SIGNING_SECRET))

    from app.main import app

    body = _form_body_for_slash({"command": "/itstatus", "text": "identity-provider"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/slack/slash",
            content=body,
            headers=_headers(body),
        )

    assert resp.status_code == 503
    assert resp.json()["detail"]["error"]["code"] == "SLASH_NOT_ENABLED"
    await close_db()


# ── 5. Signing secret unset → 503 ────────────────────────────────────────────


async def test_signing_secret_unset(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    monkeypatch.setattr(settings, "slack_slash_enabled", True)
    monkeypatch.setattr(settings, "slack_signing_secret", None)

    from app.main import app

    body = _form_body_for_slash({"command": "/itstatus", "text": "identity-provider"})
    ts = _ts_now()
    sig = _slack_sign(body, SIGNING_SECRET, ts)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/slack/slash",
            content=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
            },
        )

    assert resp.status_code == 503
    assert resp.json()["detail"]["error"]["code"] == "SLASH_NOT_CONFIGURED"
    await close_db()


# ── 6. Exact id match → 200, correct block ────────────────────────────────────


async def test_exact_id_match(slash_client):
    client, _ = slash_client
    body = _form_body_for_slash({"command": "/itstatus", "text": "identity-provider"})
    resp = await client.post("/api/slack/slash", content=body, headers=_headers(body))
    assert resp.status_code == 200
    data = resp.json()
    assert data["response_type"] == "ephemeral"
    # Header block should contain the display name
    header_texts = [b["text"]["text"] for b in data["blocks"] if b.get("type") == "header"]
    assert any("Identity Provider" in t for t in header_texts)
    # Status is operational → green check emoji
    assert "✅" in data["text"] or "Operational" in data["text"]


# ── 7. Case-insensitive display_name match → same result as exact id ──────────


async def test_case_insensitive_display_name_match(slash_client):
    client, _ = slash_client
    body = _form_body_for_slash({"command": "/itstatus", "text": "Identity Provider"})
    resp = await client.post("/api/slack/slash", content=body, headers=_headers(body))
    assert resp.status_code == 200
    data = resp.json()
    header_texts = [b["text"]["text"] for b in data["blocks"] if b.get("type") == "header"]
    assert any("Identity Provider" in t for t in header_texts)


# ── 8. Unique substring match → found ─────────────────────────────────────────


async def test_substring_match_unique(slash_client):
    """'ticket' matches only 'Ticketing' — unique → found."""
    client, _ = slash_client
    body = _form_body_for_slash({"command": "/itstatus", "text": "ticket"})
    resp = await client.post("/api/slack/slash", content=body, headers=_headers(body))
    assert resp.status_code == 200
    data = resp.json()
    header_texts = [b["text"]["text"] for b in data["blocks"] if b.get("type") == "header"]
    assert any("Ticketing" in t for t in header_texts)


# ── 9. Ambiguous substring → disambiguation text ──────────────────────────────


async def test_substring_match_ambiguous(slash_client):
    """'chat' matches both 'Chat Platform' and 'Chat Bot' but neither id exactly."""
    client, _ = slash_client
    body = _form_body_for_slash({"command": "/itstatus", "text": "chat"})
    resp = await client.post("/api/slack/slash", content=body, headers=_headers(body))
    assert resp.status_code == 200
    data = resp.json()
    text = data["text"]
    # Must mention both candidates
    assert "Chat Platform" in text or "Chat Bot" in text
    assert "more specific" in text or "Multiple" in text


# ── 10. No match → "No service matches" ──────────────────────────────────────


async def test_no_match(slash_client):
    client, _ = slash_client
    body = _form_body_for_slash({"command": "/itstatus", "text": "notaservice"})
    resp = await client.post("/api/slack/slash", content=body, headers=_headers(body))
    assert resp.status_code == 200
    data = resp.json()
    assert "No service matches" in data["text"]
    assert "notaservice" in data["text"]


# ── 11. Empty text → Usage hint ───────────────────────────────────────────────


async def test_empty_text(slash_client):
    client, _ = slash_client
    body = _form_body_for_slash({"command": "/itstatus", "text": ""})
    resp = await client.post("/api/slack/slash", content=body, headers=_headers(body))
    assert resp.status_code == 200
    data = resp.json()
    assert "Usage" in data["text"]
    assert "/itstatus" in data["text"]


# ── 12. Poller broken → "Unknown" even when current_status=operational ─────────


async def test_poller_broken_surfaces_as_unknown(slash_client):
    client, _ = slash_client
    # broken_svc has current_status=operational but poller_health=broken
    body = _form_body_for_slash({"command": "/itstatus", "text": "broken_svc"})
    resp = await client.post("/api/slack/slash", content=body, headers=_headers(body))
    assert resp.status_code == 200
    data = resp.json()
    # Should show Unknown, not Operational
    assert "Unknown" in data["text"]
    assert "Operational" not in data["text"]
    # Unknown emoji should appear
    assert "⚫" in data["text"] or "unknown" in data["text"].lower()


# ── 13. Wrong command name → 200 "Unknown slash command" ─────────────────────


async def test_wrong_command(slash_client):
    """Slack expects 200 even for unrecognised command names."""
    client, _ = slash_client
    body = _form_body_for_slash({"command": "/something-else", "text": ""})
    resp = await client.post("/api/slack/slash", content=body, headers=_headers(body))
    assert resp.status_code == 200
    data = resp.json()
    assert "Unknown slash command" in data["text"]
    assert "/something-else" in data["text"]
