"""End-to-end: poll → change detect → DB write → alert fire.

This test drives a realistic scenario through the entire production
pipeline with only the outbound HTTP calls mocked. It's the single
test that would fail if any Phase 1-3 component regressed in a way
that unit tests didn't catch, so it runs as a canary on every commit.

Scenario under test:
  1. Three polls of Statuspage return "operational" → "operational" → "major_outage".
  2. Flap suppression (threshold=2) should hold the first major_outage
     reading; the second confirms it.
  3. Change detector should emit exactly one StatusChange.
  4. The routing pipeline should produce an alert (tier=critical =>
     @here mention), record it in alert_sent_log, and increment the
     alerts_sent_total metric.
  5. The Slack webhook should receive one POST with the expected body.
"""

import asyncio

import httpx
import pytest
import respx

from app.alerting.engine import process_changes
from app.config import settings
from app.observability.metrics import ALERTS_SENT_TOTAL
from app.poller.change_detector import detect_changes
from app.poller.normalizer import ServiceStatus
from app.poller.resilience import configure_breakers
from app.poller.statuspage_poller import poll_statuspage

# Module constants (kept out of the import block so ruff I001 is satisfied)


SERVICE_ID = "e2e-svc"
POLL_URL = "https://status.e2e-example.com/api/v2/summary.json"
SLACK_WEBHOOK = "https://hooks.slack.com/services/T/B/XXXX"


async def _seed_service(db):
    await db.execute(
        """INSERT OR REPLACE INTO services
           (id, display_name, category, poll_type, poll_url,
            status_page_url, current_status, tier)
           VALUES (?, 'E2E Service', 'other', 'statuspage_json', ?,
                   'https://status.e2e-example.com', 'operational', 'critical')""",
        (SERVICE_ID, POLL_URL),
    )
    await db.commit()


def _statuspage_response(indicator: str) -> dict:
    return {
        "page": {"name": "E2E Example"},
        "status": {"indicator": indicator, "description": f"Status {indicator}"},
        "components": [],
        "incidents": [],
        "scheduled_maintenances": [],
    }


@pytest.fixture(autouse=True)
def _fast_flap_and_breakers(monkeypatch):
    """Tight thresholds for a fast test — still exercises the whole pipeline."""
    monkeypatch.setattr(settings, "alert_confirm_threshold_polls", 2)
    monkeypatch.setattr(settings, "alert_recovery_threshold_polls", 2)
    monkeypatch.setattr(settings, "alert_min_state_duration_seconds", 0)
    monkeypatch.setattr(settings, "slack_webhook_url", SLACK_WEBHOOK)
    # Fresh breakers so prior tests can't leave one open for our hostname
    configure_breakers(threshold=3, ttl_seconds=0.5)


@respx.mock
async def test_poll_change_db_alert_pipeline(db):
    """Drive the full pipeline end-to-end and assert everything reacts."""
    await _seed_service(db)

    # Mock the vendor poll endpoint: two "operational"s then a major outage.
    # Flap suppression holds the first major_outage as pending; the second
    # confirms it and emits a StatusChange.
    respx.get(POLL_URL).mock(
        side_effect=[
            httpx.Response(200, json=_statuspage_response("none")),
            httpx.Response(200, json=_statuspage_response("critical")),
            httpx.Response(200, json=_statuspage_response("critical")),
        ],
    )
    slack_route = respx.post(SLACK_WEBHOOK).mock(
        return_value=httpx.Response(200, text="ok"),
    )

    async with httpx.AsyncClient() as client:
        lock = asyncio.Lock()

        # Poll 1: operational → no change
        r1 = await poll_statuspage(client, POLL_URL)
        assert r1.status == ServiceStatus.OPERATIONAL
        changes, _ = await detect_changes(db, lock, [(SERVICE_ID, r1)])
        assert changes == []

        # Poll 2: major_outage → pending, still no change
        r2 = await poll_statuspage(client, POLL_URL)
        assert r2.status == ServiceStatus.MAJOR_OUTAGE
        changes, _ = await detect_changes(db, lock, [(SERVICE_ID, r2)])
        assert changes == []

        # Poll 3: major_outage again → confirmed, change + alert
        r3 = await poll_statuspage(client, POLL_URL)
        changes, health_changes = await detect_changes(db, lock, [(SERVICE_ID, r3)])
        assert len(changes) == 1
        assert changes[0].service_id == SERVICE_ID
        assert changes[0].previous_status == "operational"
        assert changes[0].new_status == "major_outage"
        assert health_changes == []  # Poller healthy throughout

        # DB reflects the confirmed state + status_events row
        cursor = await db.execute(
            "SELECT current_status FROM services WHERE id=?", (SERVICE_ID,),
        )
        assert (await cursor.fetchone())[0] == "major_outage"

        cursor = await db.execute(
            "SELECT count(*) FROM status_events WHERE service_id=?",
            (SERVICE_ID,),
        )
        assert (await cursor.fetchone())[0] == 1

        # Run the alerting pipeline and assert Slack got one critical-tier post
        alerts_before = ALERTS_SENT_TOTAL.labels(
            kind="status_change", severity="critical",
        )._value.get()
        await process_changes(db, lock, changes, http_client=client)

    assert slack_route.call_count == 1
    posted = slack_route.calls.last.request
    body = posted.content.decode()
    assert "E2E Service" in body
    assert "<!here>" in body  # critical tier fires an @here mention

    # Alert recorded in alert_sent_log (not suppressed)
    cursor = await db.execute(
        """SELECT suppressed_by, severity, alert_kind FROM alert_sent_log
           WHERE service_id=? ORDER BY id DESC LIMIT 1""",
        (SERVICE_ID,),
    )
    row = dict(await cursor.fetchone())
    assert row["suppressed_by"] is None
    assert row["severity"] == "critical"
    assert row["alert_kind"] == "status_change"

    # Counter incremented exactly once
    alerts_after = ALERTS_SENT_TOTAL.labels(
        kind="status_change", severity="critical",
    )._value.get()
    assert alerts_after - alerts_before == 1
