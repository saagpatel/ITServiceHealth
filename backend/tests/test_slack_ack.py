"""Tests for the Slack ack flow — Phase 2B.

Scenarios:
  - Valid sig + valid ack_alert payload → DB row updated + response_url called + 200
  - Bad signature → 403
  - Stale timestamp → 403
  - Disabled (slack_ack_enabled=False) → 404
  - Signing secret not configured → 503
  - action_id != ack_alert → 200, no-op
  - Ack button present in build_slack_alert only when ack_enabled
  - Ack button present in build_aggregated_upstream_alert only when ack_enabled
"""

import hashlib
import hmac
import json
import time
import urllib.parse

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import close_db, init_db

SERVICE_ID = "ack-test-svc"
SIGNING_SECRET = "test_signing_secret_abc"
DEDUP_KEY = "fallback:ack-test-svc:major_outage:2026-04-22"
RESPONSE_URL = "https://hooks.slack.com/actions/T/B/RESPONSE_URL_TOKEN"


# ── Signature helpers ──────────────────────────────────────────────────────────


def _slack_sign(body: bytes, secret: str, ts: str) -> str:
    """Compute a Slack v0 signature."""
    base = f"v0:{ts}:{body.decode()}"
    digest = hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return f"v0={digest}"


def _ts_now(offset: int = 0) -> str:
    return str(int(time.time()) + offset)


def _build_slack_payload(
    action_id: str = "ack_alert",
    action_value: str = DEDUP_KEY,
    username: str = "alice",
    response_url: str = RESPONSE_URL,
    original_blocks: list | None = None,
) -> dict:
    """Build a Slack block_actions JSON payload."""
    return {
        "type": "block_actions",
        "user": {"id": "U123", "username": username},
        "response_url": response_url,
        "message": {"blocks": original_blocks or []},
        "actions": [{"action_id": action_id, "value": action_value}],
    }


def _form_body(slack_payload: dict) -> bytes:
    """Encode as x-www-form-urlencoded with a `payload=` field."""
    return urllib.parse.urlencode({"payload": json.dumps(slack_payload)}).encode()


def _build_slack_headers(
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
async def ack_app(tmp_path, monkeypatch):
    """FastAPI app with ack flow enabled, backed by a real temp DB."""
    from pydantic import SecretStr

    db_path = str(tmp_path / "test.db")
    conn = await init_db(db_path)

    await conn.execute(
        """INSERT OR REPLACE INTO services
           (id, display_name, category, poll_type, poll_url, current_status, tier)
           VALUES (?, 'Ack Test Service', 'other', 'statuspage_json',
                   'https://example.com/x', 'major_outage', 'important')""",
        (SERVICE_ID,),
    )
    await conn.execute(
        """INSERT INTO status_events
           (service_id, previous_status, new_status, source, created_at)
           VALUES (?, 'operational', 'major_outage', 'statuspage_json', CURRENT_TIMESTAMP)""",
        (SERVICE_ID,),
    )
    await conn.execute(
        """INSERT INTO alert_sent_log
           (dedup_key, service_id, status_event_id, severity, new_status,
            alert_kind, suppressed_by, first_sent_at, last_updated_at)
           VALUES (?, ?, 1, 'important', 'major_outage', 'status_change',
                   NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        (DEDUP_KEY, SERVICE_ID),
    )
    await conn.commit()

    monkeypatch.setattr(settings, "slack_ack_enabled", True)
    monkeypatch.setattr(settings, "slack_signing_secret", SecretStr(SIGNING_SECRET))

    from app.main import app
    yield app, conn

    await close_db()


@pytest.fixture
async def ack_client(ack_app):
    """AsyncClient backed by the ack test app."""
    app, conn = ack_app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, conn


# ── Happy path ─────────────────────────────────────────────────────────────────


@respx.mock
async def test_valid_ack_updates_db_and_calls_response_url(ack_client):
    """Valid ack → acknowledged_at set in DB + response_url called + 200."""
    client, conn = ack_client
    response_url_route = respx.post(RESPONSE_URL).mock(
        return_value=httpx.Response(200, text="ok"),
    )

    slack_payload = _build_slack_payload()
    body = _form_body(slack_payload)
    resp = await client.post(
        "/api/slack/interactivity",
        content=body,
        headers=_build_slack_headers(body),
    )

    assert resp.status_code == 200

    cursor = await conn.execute(
        """SELECT acknowledged_at, acknowledged_by FROM alert_sent_log
           WHERE dedup_key = ?""",
        (DEDUP_KEY,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row["acknowledged_at"] is not None
    assert row["acknowledged_by"] == "alice"

    assert response_url_route.call_count == 1
    posted_body = json.loads(response_url_route.calls.last.request.content)
    assert posted_body["replace_original"] is True
    # Ack context block should mention the username
    blocks = posted_body.get("blocks", [])
    context_texts = [
        elem.get("text", "")
        for b in blocks if b.get("type") == "context"
        for elem in b.get("elements", [])
        if isinstance(elem.get("text"), str)
    ]
    assert any("alice" in t for t in context_texts)


# ── Rejection paths ────────────────────────────────────────────────────────────


async def test_bad_signature_returns_403(ack_client):
    client, _ = ack_client
    slack_payload = _build_slack_payload()
    body = _form_body(slack_payload)
    resp = await client.post(
        "/api/slack/interactivity",
        content=body,
        headers=_build_slack_headers(body, bad_sig=True),
    )
    assert resp.status_code == 403


async def test_stale_timestamp_returns_403(ack_client):
    client, _ = ack_client
    slack_payload = _build_slack_payload()
    body = _form_body(slack_payload)
    resp = await client.post(
        "/api/slack/interactivity",
        content=body,
        headers=_build_slack_headers(body, ts_offset=-400),
    )
    assert resp.status_code == 403


async def test_invalid_response_url_is_not_called(ack_client):
    client, conn = ack_client
    slack_payload = _build_slack_payload(
        response_url="https://169.254.169.254/latest/meta-data",
    )
    body = _form_body(slack_payload)
    resp = await client.post(
        "/api/slack/interactivity",
        content=body,
        headers=_build_slack_headers(body),
    )

    assert resp.status_code == 200
    cursor = await conn.execute(
        """SELECT acknowledged_at FROM alert_sent_log
           WHERE dedup_key = ?""",
        (DEDUP_KEY,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row["acknowledged_at"] is not None


async def test_disabled_returns_404(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    monkeypatch.setattr(settings, "slack_ack_enabled", False)

    from app.main import app

    body = b"payload=%7B%22type%22%3A%22block_actions%22%7D"
    ts = _ts_now()
    sig = _slack_sign(body, SIGNING_SECRET, ts)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/slack/interactivity",
            content=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
            },
        )
    assert resp.status_code == 404
    await close_db()


async def test_signing_secret_not_configured_returns_503(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    monkeypatch.setattr(settings, "slack_ack_enabled", True)
    monkeypatch.setattr(settings, "slack_signing_secret", None)

    from app.main import app

    body = b"payload=%7B%22type%22%3A%22block_actions%22%7D"
    ts = _ts_now()
    sig = _slack_sign(body, SIGNING_SECRET, ts)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/slack/interactivity",
            content=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
            },
        )
    assert resp.status_code == 503
    await close_db()


async def test_non_ack_action_id_is_no_op(ack_client):
    """Actions with a different action_id should be silently ignored (200)."""
    client, _ = ack_client
    slack_payload = _build_slack_payload(action_id="view_status_page")
    body = _form_body(slack_payload)
    resp = await client.post(
        "/api/slack/interactivity",
        content=body,
        headers=_build_slack_headers(body),
    )
    assert resp.status_code == 200


# ── Block Kit builder ack-button tests ────────────────────────────────────────


def test_ack_button_present_when_ack_enabled(monkeypatch):
    """build_slack_alert should include an ack_alert button when ack is enabled."""
    from app.alerting.slack import build_slack_alert

    monkeypatch.setattr(settings, "slack_ack_enabled", True)

    payload = build_slack_alert(
        service_name="Test Service",
        old_status="operational",
        new_status="degraded",
        impact_statement="Some impact",
        status_page_url=None,
        dedup_key="fallback:test:degraded:2026-04-22",
    )

    ack_actions = [
        b for b in payload["blocks"]
        if b.get("type") == "actions"
        and any(e.get("action_id") == "ack_alert" for e in b.get("elements", []))
    ]
    assert len(ack_actions) == 1
    btn = ack_actions[0]["elements"][0]
    assert btn["style"] == "primary"
    assert btn["value"] == "fallback:test:degraded:2026-04-22"


def test_ack_button_absent_when_ack_disabled(monkeypatch):
    """build_slack_alert must NOT include ack_alert button when disabled."""
    from app.alerting.slack import build_slack_alert

    monkeypatch.setattr(settings, "slack_ack_enabled", False)

    payload = build_slack_alert(
        service_name="Test Service",
        old_status="operational",
        new_status="degraded",
        impact_statement="Some impact",
        status_page_url=None,
        dedup_key="fallback:test:degraded:2026-04-22",
    )

    ack_actions = [
        b for b in payload["blocks"]
        if b.get("type") == "actions"
        and any(e.get("action_id") == "ack_alert" for e in b.get("elements", []))
    ]
    assert len(ack_actions) == 0


def test_ack_button_absent_when_no_dedup_key(monkeypatch):
    """build_slack_alert without a dedup_key should not have ack button even if enabled."""
    from app.alerting.slack import build_slack_alert

    monkeypatch.setattr(settings, "slack_ack_enabled", True)

    payload = build_slack_alert(
        service_name="Test Service",
        old_status="operational",
        new_status="degraded",
        impact_statement="Some impact",
        status_page_url=None,
        # no dedup_key
    )

    ack_actions = [
        b for b in payload["blocks"]
        if b.get("type") == "actions"
        and any(e.get("action_id") == "ack_alert" for e in b.get("elements", []))
    ]
    assert len(ack_actions) == 0


def test_aggregated_alert_has_ack_button_when_enabled(monkeypatch):
    """build_aggregated_upstream_alert should include ack button when ack is enabled."""
    from app.alerting.slack import build_aggregated_upstream_alert
    from app.poller.change_detector import StatusChange

    monkeypatch.setattr(settings, "slack_ack_enabled", True)

    upstream = StatusChange(
        service_id="okta",
        service_display_name="Okta",
        previous_status="operational",
        new_status="major_outage",
        status_detail=None,
        poll_type="statuspage_json",
        status_page_url=None,
    )
    dependent = StatusChange(
        service_id="box",
        service_display_name="Box",
        previous_status="operational",
        new_status="major_outage",
        status_detail=None,
        poll_type="statuspage_json",
        status_page_url=None,
    )

    payload = build_aggregated_upstream_alert(
        upstream_change=upstream,
        dependents=[dependent],
        impact_statement="Okta is down",
        dedup_key="vendor:okta:inc-999",
    )

    ack_actions = [
        b for b in payload["blocks"]
        if b.get("type") == "actions"
        and any(e.get("action_id") == "ack_alert" for e in b.get("elements", []))
    ]
    assert len(ack_actions) == 1


def test_aggregated_alert_no_ack_button_when_disabled(monkeypatch):
    """build_aggregated_upstream_alert must be byte-for-byte compatible when disabled."""
    from app.alerting.slack import build_aggregated_upstream_alert
    from app.poller.change_detector import StatusChange

    monkeypatch.setattr(settings, "slack_ack_enabled", False)

    upstream = StatusChange(
        service_id="okta",
        service_display_name="Okta",
        previous_status="operational",
        new_status="major_outage",
        status_detail=None,
        poll_type="statuspage_json",
        status_page_url=None,
    )

    payload = build_aggregated_upstream_alert(
        upstream_change=upstream,
        dependents=[],
        impact_statement="Okta is down",
        dedup_key="vendor:okta:inc-999",
    )

    ack_actions = [
        b for b in payload["blocks"]
        if b.get("type") == "actions"
        and any(e.get("action_id") == "ack_alert" for e in b.get("elements", []))
    ]
    assert len(ack_actions) == 0
