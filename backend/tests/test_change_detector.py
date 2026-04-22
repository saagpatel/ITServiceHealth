"""Tests for the change detector — status diffing, event creation, maintenance upsert."""

import asyncio

import pytest

from app.poller.change_detector import (
    PollerHealthChange,
    StatusChange,
    _compute_new_health,
    apply_manual_update,
    detect_changes,
    upsert_maintenances,
)
from app.poller.normalizer import ServiceStatus
from app.poller.statuspage_poller import PollResult


async def _insert_service(db, service_id="test-svc", status="operational", poll_type="statuspage_json"):
    """Helper: insert a test service into the DB."""
    await db.execute(
        """INSERT OR REPLACE INTO services
           (id, display_name, category, poll_type, poll_url, status_page_url, current_status)
           VALUES (?, ?, 'other', ?, 'https://example.com', 'https://status.example.com', ?)""",
        (service_id, service_id.title(), poll_type, status),
    )
    await db.commit()


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
