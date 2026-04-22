"""Tests for the alerting routing pipeline (Phase 2)."""

import pytest

from app.alerting.routing import (
    build_dedup_key,
    find_aggregation_candidates,
    is_in_maintenance_window,
    record_alert,
    route_status_change,
    was_recently_alerted,
)
from app.config import settings
from app.poller.change_detector import StatusChange


async def _insert_service(
    db, sid, status="operational", tier="important", override=None,
):
    await db.execute(
        """INSERT OR REPLACE INTO services
           (id, display_name, category, poll_type, poll_url,
            status_page_url, current_status, tier, slack_channel_override)
           VALUES (?, ?, 'other', 'statuspage_json', 'https://example.com/x',
                   'https://status.example.com', ?, ?, ?)""",
        (sid, sid.title(), status, tier, override),
    )
    await db.commit()


def _make_change(service_id, new_status="degraded", prev_status="operational", event_id=None):
    return StatusChange(
        service_id=service_id,
        service_display_name=service_id.title(),
        previous_status=prev_status,
        new_status=new_status,
        status_detail="test",
        poll_type="statuspage_json",
        status_page_url="https://status.example.com",
        event_id=event_id,
    )


class TestDedupKey:
    def test_vendor_id_preferred(self):
        key = build_dedup_key("box", "degraded", vendor_incident_id="inc-123")
        assert key == "vendor:box:inc-123"

    def test_fallback_when_no_vendor_id(self):
        key = build_dedup_key("box", "degraded", vendor_incident_id=None)
        assert key.startswith("fallback:box:degraded:")

    def test_different_statuses_different_keys(self):
        a = build_dedup_key("box", "degraded", None)
        b = build_dedup_key("box", "major_outage", None)
        assert a != b


class TestMaintenanceWindow:
    async def test_no_window_returns_false(self, db):
        await _insert_service(db, "noclash")
        assert not await is_in_maintenance_window(db, "noclash")

    async def test_active_window_returns_true(self, db):
        await _insert_service(db, "maint")
        # Insert a maintenance window covering right now
        await db.execute(
            """INSERT INTO scheduled_maintenances
               (service_id, vendor_maintenance_id, title, scheduled_for,
                scheduled_until, status)
               VALUES (?, ?, ?, datetime('now', '-1 hour'),
                       datetime('now', '+1 hour'), 'in_progress')""",
            ("maint", "m1", "test"),
        )
        await db.commit()
        assert await is_in_maintenance_window(db, "maint")

    async def test_future_window_returns_false(self, db):
        await _insert_service(db, "future")
        await db.execute(
            """INSERT INTO scheduled_maintenances
               (service_id, vendor_maintenance_id, title, scheduled_for,
                scheduled_until, status)
               VALUES (?, ?, ?, datetime('now', '+2 hours'),
                       datetime('now', '+3 hours'), 'scheduled')""",
            ("future", "m2", "upcoming"),
        )
        await db.commit()
        assert not await is_in_maintenance_window(db, "future")


class TestWasRecentlyAlerted:
    async def test_fresh_dedup_key_returns_false(self, db):
        assert not await was_recently_alerted(db, "vendor:box:new", 3600)

    async def test_recent_same_key_returns_true(self, db):
        await _insert_service(db, "box")
        await db.execute(
            """INSERT INTO alert_sent_log
               (dedup_key, service_id, severity, new_status, alert_kind,
                first_sent_at, last_updated_at)
               VALUES ('vendor:box:inc-1', 'box', 'important', 'degraded',
                       'status_change', datetime('now', '-2 minutes'),
                       datetime('now', '-2 minutes'))"""
        )
        await db.commit()
        assert await was_recently_alerted(db, "vendor:box:inc-1", 3600)

    async def test_outside_window_returns_false(self, db):
        await _insert_service(db, "box")
        await db.execute(
            """INSERT INTO alert_sent_log
               (dedup_key, service_id, severity, new_status, alert_kind,
                first_sent_at, last_updated_at)
               VALUES ('vendor:box:old', 'box', 'important', 'degraded',
                       'status_change', datetime('now', '-25 hours'),
                       datetime('now', '-25 hours'))"""
        )
        await db.commit()
        assert not await was_recently_alerted(db, "vendor:box:old", 86400)

    async def test_suppressed_rows_ignored(self, db):
        """A suppressed alert doesn't count toward dedup — it didn't actually fire."""
        await _insert_service(db, "box")
        await db.execute(
            """INSERT INTO alert_sent_log
               (dedup_key, service_id, severity, new_status, alert_kind,
                suppressed_by, first_sent_at, last_updated_at)
               VALUES ('vendor:box:supp', 'box', 'important', 'degraded',
                       'status_change', 'maintenance_window',
                       datetime('now', '-2 minutes'),
                       datetime('now', '-2 minutes'))"""
        )
        await db.commit()
        assert not await was_recently_alerted(db, "vendor:box:supp", 3600)


class TestRouteStatusChange:
    @pytest.fixture(autouse=True)
    def _webhook_set(self, monkeypatch):
        monkeypatch.setattr(
            settings, "slack_webhook_url",
            "https://hooks.slack.com/services/x/y/z",
        )

    async def test_critical_tier_adds_here_mention(self, db):
        await _insert_service(db, "okta", tier="critical")
        decision = await route_status_change(db, _make_change("okta"))
        assert decision.should_send
        assert decision.channel_mention == "<!here>"
        assert decision.tier == "critical"
        assert decision.suppressed_by is None

    async def test_important_tier_no_mention(self, db):
        await _insert_service(db, "box", tier="important")
        decision = await route_status_change(db, _make_change("box"))
        assert decision.should_send
        assert decision.channel_mention is None
        assert decision.tier == "important"

    async def test_informational_tier_is_suppressed(self, db):
        await _insert_service(db, "minor", tier="informational")
        decision = await route_status_change(db, _make_change("minor"))
        assert not decision.should_send
        assert decision.suppressed_by == "tier_informational"

    async def test_maintenance_window_suppresses(self, db):
        await _insert_service(db, "maint", tier="critical")
        await db.execute(
            """INSERT INTO scheduled_maintenances
               (service_id, vendor_maintenance_id, title, scheduled_for,
                scheduled_until, status)
               VALUES ('maint', 'm1', 'test',
                       datetime('now', '-1 hour'),
                       datetime('now', '+1 hour'), 'in_progress')"""
        )
        await db.commit()
        decision = await route_status_change(db, _make_change("maint"))
        assert not decision.should_send
        assert decision.suppressed_by == "maintenance_window"

    async def test_recent_dedup_suppresses(self, db):
        await _insert_service(db, "dup", tier="important")
        change = _make_change("dup")
        # Seed a recent alert with the fallback dedup_key this change will use
        dedup_key = build_dedup_key("dup", "degraded", None)
        await db.execute(
            """INSERT INTO alert_sent_log
               (dedup_key, service_id, severity, new_status, alert_kind,
                first_sent_at, last_updated_at)
               VALUES (?, ?, 'important', 'degraded', 'status_change',
                       datetime('now', '-2 minutes'),
                       datetime('now', '-2 minutes'))""",
            (dedup_key, "dup"),
        )
        await db.commit()
        decision = await route_status_change(db, change)
        assert not decision.should_send
        assert decision.suppressed_by == "dedup"

    async def test_recovery_bypasses_dedup(self, db):
        """Recoveries should never be deduplicated — users want to know 'it's back'."""
        await _insert_service(db, "rec", tier="important")
        dedup_key = build_dedup_key("rec", "operational", None)
        await db.execute(
            """INSERT INTO alert_sent_log
               (dedup_key, service_id, severity, new_status, alert_kind,
                first_sent_at, last_updated_at)
               VALUES (?, ?, 'important', 'operational', 'status_change',
                       datetime('now', '-2 minutes'),
                       datetime('now', '-2 minutes'))""",
            (dedup_key, "rec"),
        )
        await db.commit()
        change = _make_change("rec", new_status="operational", prev_status="degraded")
        decision = await route_status_change(db, change)
        assert decision.should_send

    async def test_aggregated_under_suppresses(self, db):
        await _insert_service(db, "dep", tier="critical")
        decision = await route_status_change(
            db, _make_change("dep"), aggregated_under="Okta",
        )
        assert not decision.should_send
        assert decision.suppressed_by == "aggregated_under_upstream"
        assert decision.aggregated_under == "Okta"

    async def test_no_webhook_is_recorded_as_suppressed(self, db, monkeypatch):
        monkeypatch.setattr(settings, "slack_webhook_url", None)
        await _insert_service(db, "nohook", tier="important")
        decision = await route_status_change(db, _make_change("nohook"))
        assert not decision.should_send
        assert decision.suppressed_by == "webhook_not_configured"


class TestRecordAlert:
    async def test_records_fired_alert(self, db):
        await _insert_service(db, "box")
        change = _make_change("box")
        from app.alerting.routing import RoutingDecision
        decision = RoutingDecision(
            should_send=True,
            webhook_url="https://example.com",
            channel_mention=None,
            dedup_key="vendor:box:x",
            tier="important",
            suppressed_by=None,
        )
        await record_alert(db, change, decision)
        await db.commit()
        cursor = await db.execute(
            "SELECT suppressed_by, tier_col FROM alert_sent_log WHERE dedup_key='vendor:box:x'"
            .replace("tier_col", "severity")  # table uses `severity` col name
        )
        row = await cursor.fetchone()
        assert row is not None
        assert dict(row)["severity"] == "important"
        assert dict(row)["suppressed_by"] is None

    async def test_records_suppressed_alert(self, db):
        await _insert_service(db, "box")
        change = _make_change("box")
        from app.alerting.routing import RoutingDecision
        decision = RoutingDecision(
            should_send=False,
            webhook_url=None,
            channel_mention=None,
            dedup_key="vendor:box:y",
            tier="informational",
            suppressed_by="tier_informational",
        )
        await record_alert(db, change, decision)
        await db.commit()
        cursor = await db.execute(
            "SELECT suppressed_by FROM alert_sent_log WHERE dedup_key='vendor:box:y'"
        )
        row = dict(await cursor.fetchone())
        assert row["suppressed_by"] == "tier_informational"


class TestAggregationCandidates:
    async def _insert_dep(self, db, upstream, downstream, severity="high"):
        await db.execute(
            """INSERT INTO service_dependencies
               (upstream_service_id, downstream_service_id, impact_description, severity)
               VALUES (?, ?, 'test', ?)""",
            (upstream, downstream, severity),
        )
        await db.commit()

    async def test_aggregates_when_threshold_met(self, db):
        for sid in ["okta", "a", "b", "c", "d"]:
            await _insert_service(db, sid)
        for dep in ["a", "b", "c", "d"]:
            await self._insert_dep(db, "okta", dep)

        changes = [
            _make_change("okta", "major_outage"),
            _make_change("a", "degraded"),
            _make_change("b", "degraded"),
            _make_change("c", "degraded"),
            _make_change("d", "operational"),  # not affected → ignored
        ]
        grouped = await find_aggregation_candidates(db, changes, threshold=3)
        assert "okta" in grouped
        assert len(grouped["okta"]) == 3
        assert {c.service_id for c in grouped["okta"]} == {"a", "b", "c"}

    async def test_no_aggregation_when_below_threshold(self, db):
        for sid in ["okta", "a", "b"]:
            await _insert_service(db, sid)
        await self._insert_dep(db, "okta", "a")
        await self._insert_dep(db, "okta", "b")

        changes = [
            _make_change("okta", "degraded"),
            _make_change("a", "degraded"),
        ]
        grouped = await find_aggregation_candidates(db, changes, threshold=3)
        assert grouped == {}

    async def test_upstream_recovering_does_not_aggregate(self, db):
        for sid in ["okta", "a", "b", "c"]:
            await _insert_service(db, sid)
        for dep in ["a", "b", "c"]:
            await self._insert_dep(db, "okta", dep)

        changes = [
            _make_change("okta", new_status="operational", prev_status="major_outage"),
            _make_change("a", "degraded"),
            _make_change("b", "degraded"),
            _make_change("c", "degraded"),
        ]
        grouped = await find_aggregation_candidates(db, changes, threshold=3)
        # Upstream going back to operational isn't an outage event to aggregate
        assert "okta" not in grouped
