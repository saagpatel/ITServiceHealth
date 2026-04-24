"""Tests for the change detector — status diffing, event creation, maintenance upsert."""

import asyncio

import pytest

from app.config import settings
from app.poller.change_detector import (
    PollerHealthChange,
    _compute_new_health,
    _extract_vendor_incident_id,
    _is_going_worse,
    _update_pending,
    apply_manual_update,
    detect_changes,
    upsert_maintenances,
)
from app.poller.normalizer import ServiceStatus
from app.poller.statuspage_poller import PollResult


@pytest.fixture
def _no_flap_suppression(monkeypatch):
    """Disable flap suppression so legacy tests still assert immediate flips.
    Flap-specific tests use their own explicit thresholds."""
    monkeypatch.setattr(settings, "alert_confirm_threshold_polls", 1)
    monkeypatch.setattr(settings, "alert_recovery_threshold_polls", 1)
    monkeypatch.setattr(settings, "alert_min_state_duration_seconds", 0)


async def _insert_service(db, service_id="test-svc", status="operational", poll_type="statuspage_json"):
    """Helper: insert a test service into the DB."""
    await db.execute(
        """INSERT OR REPLACE INTO services
           (id, display_name, category, poll_type, poll_url, status_page_url, current_status)
           VALUES (?, ?, 'other', ?, 'https://example.com', 'https://status.example.com', ?)""",
        (service_id, service_id.title(), poll_type, status),
    )
    await db.commit()


@pytest.mark.usefixtures("_no_flap_suppression")
class TestDetectChanges:
    async def test_status_change_creates_event(self, db):
        await _insert_service(db, "svc-a", "operational")
        lock = asyncio.Lock()

        result = PollResult(status=ServiceStatus.DEGRADED, status_detail="Slow responses")
        changes, health_changes = await detect_changes(db, lock, [("svc-a", result)])

        assert len(changes) == 1
        assert changes[0].previous_status == "operational"
        assert changes[0].new_status == "degraded"
        assert changes[0].status_detail == "Slow responses"
        assert health_changes == []

        cursor = await db.execute("SELECT * FROM status_events WHERE service_id='svc-a'")
        events = await cursor.fetchall()
        assert len(events) == 1
        assert dict(events[0])["previous_status"] == "operational"
        assert dict(events[0])["new_status"] == "degraded"

    async def test_status_change_updates_service(self, db):
        await _insert_service(db, "svc-b", "operational")
        lock = asyncio.Lock()

        result = PollResult(status=ServiceStatus.MAJOR_OUTAGE, status_detail="Down")
        await detect_changes(db, lock, [("svc-b", result)])

        cursor = await db.execute(
            """SELECT current_status, current_status_detail, last_status_change_at,
                     last_success_at, poller_health
               FROM services WHERE id='svc-b'"""
        )
        row = dict(await cursor.fetchone())
        assert row["current_status"] == "major_outage"
        assert row["current_status_detail"] == "Down"
        assert row["last_status_change_at"] is not None
        assert row["last_success_at"] is not None
        assert row["poller_health"] == "healthy"

    async def test_no_change_updates_polled_at(self, db):
        await _insert_service(db, "svc-c", "operational")
        lock = asyncio.Lock()

        result = PollResult(status=ServiceStatus.OPERATIONAL, status_detail="All good")
        changes, health_changes = await detect_changes(db, lock, [("svc-c", result)])

        assert len(changes) == 0
        assert health_changes == []

        cursor = await db.execute("SELECT last_polled_at, current_status_detail FROM services WHERE id='svc-c'")
        row = dict(await cursor.fetchone())
        assert row["last_polled_at"] is not None
        assert row["current_status_detail"] == "All good"

    async def test_no_change_does_not_create_event(self, db):
        await _insert_service(db, "svc-d", "degraded")
        lock = asyncio.Lock()

        result = PollResult(status=ServiceStatus.DEGRADED)
        await detect_changes(db, lock, [("svc-d", result)])

        cursor = await db.execute("SELECT count(*) FROM status_events WHERE service_id='svc-d'")
        assert (await cursor.fetchone())[0] == 0

    async def test_unknown_preserves_current_status(self, db):
        await _insert_service(db, "svc-e", "operational")
        lock = asyncio.Lock()

        result = PollResult(
            status=ServiceStatus.UNKNOWN,
            status_detail="Poll timeout",
            poll_failure_reason="timeout",
        )
        changes, health_changes = await detect_changes(db, lock, [("svc-e", result)])

        assert len(changes) == 0
        assert health_changes == []  # One failure isn't enough to flip to broken

        cursor = await db.execute(
            """SELECT current_status, last_polled_at, consecutive_failures,
                     last_failure_reason, poller_health
               FROM services WHERE id='svc-e'"""
        )
        row = dict(await cursor.fetchone())
        assert row["current_status"] == "operational"  # Preserved!
        assert row["last_polled_at"] is not None
        assert row["consecutive_failures"] == 1
        assert row["last_failure_reason"] == "timeout"
        assert row["poller_health"] == "degraded"

    async def test_multiple_changes_in_batch(self, db):
        await _insert_service(db, "svc-f", "operational")
        await _insert_service(db, "svc-g", "operational")
        await _insert_service(db, "svc-h", "degraded")
        lock = asyncio.Lock()

        results = [
            ("svc-f", PollResult(status=ServiceStatus.DEGRADED)),
            ("svc-g", PollResult(status=ServiceStatus.OPERATIONAL)),  # no change
            ("svc-h", PollResult(status=ServiceStatus.MAJOR_OUTAGE)),
        ]
        changes, health_changes = await detect_changes(db, lock, results)

        assert len(changes) == 2
        changed_ids = {c.service_id for c in changes}
        assert changed_ids == {"svc-f", "svc-h"}
        assert health_changes == []

    async def test_empty_results(self, db):
        lock = asyncio.Lock()
        result = await detect_changes(db, lock, [])
        assert result == ([], [])


class TestPollerHealthStateMachine:
    def test_success_always_clears(self):
        assert _compute_new_health("broken", 0, True, threshold=3) == "healthy"
        assert _compute_new_health("degraded", 0, True, threshold=3) == "healthy"
        assert _compute_new_health("healthy", 0, True, threshold=3) == "healthy"

    def test_single_failure_is_degraded(self):
        assert _compute_new_health("healthy", 1, False, threshold=3) == "degraded"

    def test_threshold_flip_to_broken(self):
        assert _compute_new_health("degraded", 3, False, threshold=3) == "broken"

    def test_above_threshold_stays_broken(self):
        assert _compute_new_health("broken", 10, False, threshold=3) == "broken"


class TestFlapSuppressionStateMachine:
    """Pure unit tests for `_update_pending` — no DB, no I/O."""

    NOW_STR = "2026-05-01T00:00:00Z"
    from datetime import datetime, timezone
    NOW_DT = datetime.fromisoformat(NOW_STR.replace("Z", "+00:00"))

    def test_same_status_clears_pending(self):
        d = _update_pending(
            poll_status="operational",
            current_status="operational",
            pending_status="degraded",
            pending_count=2,
            pending_since="2026-05-01T00:00:00Z",
            now=self.NOW_STR, now_dt=self.NOW_DT,
            confirm_threshold=3, recovery_threshold=2,
            min_state_duration_seconds=0,
        )
        assert d.new_pending_status is None
        assert d.new_pending_count == 0
        assert d.promoted_status is None

    def test_first_observation_sets_pending_to_one(self):
        d = _update_pending(
            poll_status="degraded",
            current_status="operational",
            pending_status=None,
            pending_count=0,
            pending_since=None,
            now=self.NOW_STR, now_dt=self.NOW_DT,
            confirm_threshold=3, recovery_threshold=2,
            min_state_duration_seconds=0,
        )
        assert d.new_pending_status == "degraded"
        assert d.new_pending_count == 1
        assert d.promoted_status is None

    def test_increments_on_matching_target(self):
        d = _update_pending(
            poll_status="degraded",
            current_status="operational",
            pending_status="degraded",
            pending_count=1,
            pending_since=self.NOW_STR,
            now=self.NOW_STR, now_dt=self.NOW_DT,
            confirm_threshold=3, recovery_threshold=2,
            min_state_duration_seconds=0,
        )
        assert d.new_pending_count == 2
        assert d.promoted_status is None

    def test_promotes_when_confirm_threshold_met(self):
        d = _update_pending(
            poll_status="degraded",
            current_status="operational",
            pending_status="degraded",
            pending_count=2,          # +1 this poll = 3
            pending_since=self.NOW_STR,
            now=self.NOW_STR, now_dt=self.NOW_DT,
            confirm_threshold=3, recovery_threshold=2,
            min_state_duration_seconds=0,
        )
        assert d.promoted_status == "degraded"
        assert d.new_pending_status is None

    def test_recovery_uses_lower_threshold(self):
        d = _update_pending(
            poll_status="operational",
            current_status="degraded",
            pending_status="operational",
            pending_count=1,          # +1 this poll = 2
            pending_since=self.NOW_STR,
            now=self.NOW_STR, now_dt=self.NOW_DT,
            confirm_threshold=3, recovery_threshold=2,
            min_state_duration_seconds=600,  # dwell IGNORED for recovery
        )
        assert d.promoted_status == "operational"

    def test_min_dwell_blocks_promote_for_worsening(self):
        # Count threshold met, but only 30s elapsed vs 600s minimum dwell
        from datetime import timedelta
        since = "2026-05-01T00:00:00Z"
        now = self.NOW_DT + timedelta(seconds=30)
        d = _update_pending(
            poll_status="major_outage",
            current_status="operational",
            pending_status="major_outage",
            pending_count=2,         # +1 = 3, meets count threshold
            pending_since=since,
            now=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            now_dt=now,
            confirm_threshold=3, recovery_threshold=2,
            min_state_duration_seconds=600,
        )
        # Dwell not met yet — still pending
        assert d.promoted_status is None
        assert d.new_pending_count == 3

    def test_min_dwell_allows_promote_once_elapsed(self):
        from datetime import timedelta
        since = "2026-05-01T00:00:00Z"
        now = self.NOW_DT + timedelta(seconds=700)
        d = _update_pending(
            poll_status="major_outage",
            current_status="operational",
            pending_status="major_outage",
            pending_count=2,
            pending_since=since,
            now=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            now_dt=now,
            confirm_threshold=3, recovery_threshold=2,
            min_state_duration_seconds=600,
        )
        assert d.promoted_status == "major_outage"

    def test_different_target_resets_buffer(self):
        """Flapping between degraded and major_outage resets to count=1."""
        d = _update_pending(
            poll_status="major_outage",
            current_status="operational",
            pending_status="degraded",   # was pending degraded
            pending_count=2,
            pending_since=self.NOW_STR,
            now=self.NOW_STR, now_dt=self.NOW_DT,
            confirm_threshold=3, recovery_threshold=2,
            min_state_duration_seconds=0,
        )
        assert d.new_pending_status == "major_outage"
        assert d.new_pending_count == 1

    def test_is_going_worse_helper(self):
        assert _is_going_worse("operational", "degraded")
        assert _is_going_worse("degraded", "major_outage")
        assert not _is_going_worse("degraded", "operational")
        assert not _is_going_worse("operational", "operational")


class TestFlapSuppressionIntegration:
    """End-to-end: drive detect_changes across multiple polls to confirm
    flap suppression actually keeps us quiet."""

    async def _set_thresholds(self, monkeypatch, confirm, recovery, dwell):
        monkeypatch.setattr(settings, "alert_confirm_threshold_polls", confirm)
        monkeypatch.setattr(settings, "alert_recovery_threshold_polls", recovery)
        monkeypatch.setattr(settings, "alert_min_state_duration_seconds", dwell)

    async def test_single_blip_produces_zero_alerts(self, db, monkeypatch):
        await self._set_thresholds(monkeypatch, confirm=3, recovery=2, dwell=0)
        await _insert_service(db, "flap", "operational")
        lock = asyncio.Lock()

        # One poll showing degraded, then back to operational
        changes1, _ = await detect_changes(db, lock, [("flap", PollResult(status=ServiceStatus.DEGRADED))])
        changes2, _ = await detect_changes(db, lock, [("flap", PollResult(status=ServiceStatus.OPERATIONAL))])

        assert changes1 == []
        assert changes2 == []

        cursor = await db.execute(
            "SELECT current_status, pending_status, pending_status_count FROM services WHERE id='flap'"
        )
        row = dict(await cursor.fetchone())
        assert row["current_status"] == "operational"  # Never flipped
        assert row["pending_status"] is None           # Cleared on return to stable

    async def test_three_polls_confirm_status_change(self, db, monkeypatch):
        await self._set_thresholds(monkeypatch, confirm=3, recovery=2, dwell=0)
        await _insert_service(db, "confirm", "operational")
        lock = asyncio.Lock()

        # First poll — pending, no change
        c1, _ = await detect_changes(db, lock, [("confirm", PollResult(status=ServiceStatus.DEGRADED))])
        assert c1 == []
        # Second poll — still pending
        c2, _ = await detect_changes(db, lock, [("confirm", PollResult(status=ServiceStatus.DEGRADED))])
        assert c2 == []
        # Third poll — promoted
        c3, _ = await detect_changes(db, lock, [("confirm", PollResult(status=ServiceStatus.DEGRADED))])
        assert len(c3) == 1
        assert c3[0].new_status == "degraded"

    async def test_different_pending_targets_reset_counter(self, db, monkeypatch):
        await self._set_thresholds(monkeypatch, confirm=3, recovery=2, dwell=0)
        await _insert_service(db, "mixed", "operational")
        lock = asyncio.Lock()

        # Degraded x 2, then major_outage x 2 — should NOT promote
        # because the target changed mid-stream.
        for _ in range(2):
            await detect_changes(db, lock, [("mixed", PollResult(status=ServiceStatus.DEGRADED))])
        for _ in range(2):
            c, _ = await detect_changes(db, lock, [("mixed", PollResult(status=ServiceStatus.MAJOR_OUTAGE))])

        # Only 2 consecutive major_outage polls, threshold is 3 → no promote
        assert c == []
        cursor = await db.execute("SELECT current_status FROM services WHERE id='mixed'")
        assert dict(await cursor.fetchone())["current_status"] == "operational"

    async def test_recovery_promotes_after_two_polls(self, db, monkeypatch):
        await self._set_thresholds(monkeypatch, confirm=3, recovery=2, dwell=0)
        await _insert_service(db, "rec", "degraded")
        lock = asyncio.Lock()

        c1, _ = await detect_changes(db, lock, [("rec", PollResult(status=ServiceStatus.OPERATIONAL))])
        c2, _ = await detect_changes(db, lock, [("rec", PollResult(status=ServiceStatus.OPERATIONAL))])

        assert c1 == []
        assert len(c2) == 1
        assert c2[0].new_status == "operational"


@pytest.mark.usefixtures("_no_flap_suppression")
class TestPollerHealthTransitions:
    async def test_three_failures_flip_to_broken(self, db):
        await _insert_service(db, "flaky", "operational")
        lock = asyncio.Lock()

        fail = PollResult(
            status=ServiceStatus.UNKNOWN,
            status_detail="gone",
            poll_failure_reason="request_error: ConnectError",
        )

        # Two failures — still just degraded
        await detect_changes(db, lock, [("flaky", fail)])
        _, hc2 = await detect_changes(db, lock, [("flaky", fail)])
        assert hc2 == []

        # Third failure trips the threshold
        _, hc3 = await detect_changes(db, lock, [("flaky", fail)])
        assert len(hc3) == 1
        assert isinstance(hc3[0], PollerHealthChange)
        assert hc3[0].service_id == "flaky"
        assert hc3[0].new_health == "broken"
        assert hc3[0].previous_health == "degraded"
        assert hc3[0].consecutive_failures == 3
        assert hc3[0].failure_reason == "request_error: ConnectError"

    async def test_recovery_emits_transition(self, db):
        await _insert_service(db, "recov", "operational")
        lock = asyncio.Lock()

        fail = PollResult(
            status=ServiceStatus.UNKNOWN,
            poll_failure_reason="timeout",
        )
        good = PollResult(status=ServiceStatus.OPERATIONAL)

        # Drive to broken
        await detect_changes(db, lock, [("recov", fail)])
        await detect_changes(db, lock, [("recov", fail)])
        _, hc_broken = await detect_changes(db, lock, [("recov", fail)])
        assert hc_broken[0].new_health == "broken"

        # Next success should recover + emit a health change back to healthy
        _, hc_recover = await detect_changes(db, lock, [("recov", good)])
        assert len(hc_recover) == 1
        assert hc_recover[0].previous_health == "broken"
        assert hc_recover[0].new_health == "healthy"
        assert hc_recover[0].consecutive_failures == 0

    async def test_degraded_to_broken_only_fires_once(self, db):
        await _insert_service(db, "once", "operational")
        lock = asyncio.Lock()

        fail = PollResult(
            status=ServiceStatus.UNKNOWN,
            poll_failure_reason="timeout",
        )

        # Go broken
        for _ in range(3):
            await detect_changes(db, lock, [("once", fail)])

        # Additional failures while already broken should not re-emit
        _, hc = await detect_changes(db, lock, [("once", fail)])
        assert hc == []


class TestApplyManualUpdate:
    async def test_manual_update_creates_event(self, db):
        await _insert_service(db, "manual-svc", "operational", "manual")
        lock = asyncio.Lock()

        change = await apply_manual_update(db, lock, "manual-svc", ServiceStatus.DEGRADED, "Slow")

        assert change is not None
        assert change.previous_status == "operational"
        assert change.new_status == "degraded"
        assert change.poll_type == "manual"

        cursor = await db.execute("SELECT source FROM status_events WHERE service_id='manual-svc'")
        row = await cursor.fetchone()
        assert dict(row)["source"] == "manual"

    async def test_manual_update_same_status_returns_none(self, db):
        await _insert_service(db, "manual-svc2", "degraded", "manual")
        lock = asyncio.Lock()

        change = await apply_manual_update(db, lock, "manual-svc2", ServiceStatus.DEGRADED, "Still slow")
        assert change is None

    async def test_manual_update_nonexistent_service(self, db):
        lock = asyncio.Lock()
        with pytest.raises(ValueError, match="not found"):
            await apply_manual_update(db, lock, "nonexistent", ServiceStatus.DEGRADED, None)


class TestExtractVendorIncidentId:
    """Unit tests for _extract_vendor_incident_id — no DB, no I/O."""

    def test_returns_id_from_first_incident(self):
        result = PollResult(
            status=ServiceStatus.DEGRADED,
            incidents=[{"id": "abc123", "status": "investigating", "name": "API latency"}],
        )
        assert _extract_vendor_incident_id(result) == "abc123"

    def test_returns_none_when_no_incidents(self):
        result = PollResult(status=ServiceStatus.DEGRADED, incidents=[])
        assert _extract_vendor_incident_id(result) is None

    def test_returns_none_when_id_missing_from_dict(self):
        result = PollResult(
            status=ServiceStatus.DEGRADED,
            incidents=[{"status": "investigating"}],
        )
        assert _extract_vendor_incident_id(result) is None

    def test_coerces_id_to_str(self):
        result = PollResult(
            status=ServiceStatus.DEGRADED,
            incidents=[{"id": 99, "status": "investigating"}],
        )
        assert _extract_vendor_incident_id(result) == "99"


@pytest.mark.usefixtures("_no_flap_suppression")
class TestVendorIncidentIdWiring:
    """Integration: vendor_incident_id flows from PollResult → status_events → StatusChange."""

    async def test_vendor_incident_id_populated_from_statuspage_incidents(self, db):
        await _insert_service(db, "svc-inc", "operational")
        lock = asyncio.Lock()

        result = PollResult(
            status=ServiceStatus.DEGRADED,
            status_detail="API latency elevated",
            incidents=[{"id": "abc123", "status": "investigating", "name": "API latency"}],
        )
        changes, _ = await detect_changes(db, lock, [("svc-inc", result)])

        assert len(changes) == 1
        assert changes[0].vendor_incident_id == "abc123"

        cursor = await db.execute(
            "SELECT vendor_incident_id FROM status_events WHERE service_id='svc-inc'"
        )
        row = dict(await cursor.fetchone())
        assert row["vendor_incident_id"] == "abc123"

    async def test_vendor_incident_id_null_when_no_incidents(self, db):
        await _insert_service(db, "svc-noinc", "operational")
        lock = asyncio.Lock()

        result = PollResult(
            status=ServiceStatus.DEGRADED,
            status_detail="All systems operational",
            incidents=[],
        )
        changes, _ = await detect_changes(db, lock, [("svc-noinc", result)])

        assert len(changes) == 1
        assert changes[0].vendor_incident_id is None

        cursor = await db.execute(
            "SELECT vendor_incident_id FROM status_events WHERE service_id='svc-noinc'"
        )
        row = dict(await cursor.fetchone())
        assert row["vendor_incident_id"] is None


class TestUpsertMaintenances:
    async def test_insert_new_maintenance(self, db):
        await _insert_service(db, "maint-svc", "operational")

        maintenances = [{
            "id": "maint-001",
            "name": "Database migration",
            "scheduled_for": "2026-04-10T02:00:00Z",
            "scheduled_until": "2026-04-10T04:00:00Z",
            "status": "scheduled",
            "incident_updates": [{"body": "Planned DB migration"}],
        }]

        await upsert_maintenances(db, "maint-svc", maintenances)
        await db.commit()

        cursor = await db.execute("SELECT * FROM scheduled_maintenances WHERE service_id='maint-svc'")
        rows = await cursor.fetchall()
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["vendor_maintenance_id"] == "maint-001"
        assert row["title"] == "Database migration"
        assert row["status"] == "scheduled"

    async def test_upsert_updates_existing(self, db):
        await _insert_service(db, "maint-svc2", "operational")

        m = [{
            "id": "maint-002",
            "name": "API maintenance",
            "scheduled_for": "2026-04-10T02:00:00Z",
            "status": "scheduled",
            "incident_updates": [],
        }]
        await upsert_maintenances(db, "maint-svc2", m)
        await db.commit()

        # Update status to in_progress
        m[0]["status"] = "in_progress"
        await upsert_maintenances(db, "maint-svc2", m)
        await db.commit()

        cursor = await db.execute("SELECT count(*) FROM scheduled_maintenances WHERE service_id='maint-svc2'")
        assert (await cursor.fetchone())[0] == 1  # Still just one row

        cursor = await db.execute("SELECT status FROM scheduled_maintenances WHERE vendor_maintenance_id='maint-002'")
        assert dict(await cursor.fetchone())["status"] == "in_progress"

    async def test_skips_maintenance_without_id(self, db):
        await _insert_service(db, "maint-svc3", "operational")
        await upsert_maintenances(db, "maint-svc3", [{"name": "No ID"}])
        await db.commit()

        cursor = await db.execute("SELECT count(*) FROM scheduled_maintenances WHERE service_id='maint-svc3'")
        assert (await cursor.fetchone())[0] == 0
