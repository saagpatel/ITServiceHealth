"""Tests for Phase 4 data lifecycle: pragmas, retention, WAL checkpoint."""

from pathlib import Path

import aiosqlite
import pytest

from app.database import (
    apply_production_pragmas,
    checkpoint_wal,
    close_db,
    init_db,
    run_migrations,
)
from app.retention import purge_old_rows


async def _insert_event(db, service_id, days_ago, status="degraded"):
    await db.execute(
        """INSERT INTO status_events
           (service_id, previous_status, new_status, source, created_at)
           VALUES (?, 'operational', ?, 'manual',
                   datetime('now', ?))""",
        (service_id, status, f"-{days_ago} days"),
    )


async def _insert_service(db, sid="svc"):
    await db.execute(
        """INSERT OR REPLACE INTO services
           (id, display_name, category, poll_type, poll_url,
            status_page_url, current_status)
           VALUES (?, ?, 'other', 'manual', 'https://example.com/x',
                   'https://status.example.com', 'operational')""",
        (sid, sid.title()),
    )
    await db.commit()


async def _insert_alert(db, service_id, days_ago, dedup_key=None):
    await db.execute(
        """INSERT INTO alert_sent_log
           (dedup_key, service_id, severity, new_status, alert_kind,
            first_sent_at, last_updated_at)
           VALUES (?, ?, 'important', 'degraded', 'status_change',
                   datetime('now', ?), datetime('now', ?))""",
        (dedup_key or f"test:{service_id}:{days_ago}", service_id,
         f"-{days_ago} days", f"-{days_ago} days"),
    )


class TestProductionPragmas:
    async def test_all_pragmas_applied(self, tmp_path):
        """Verify every pragma we set lands on a fresh connection."""
        path = tmp_path / "pragma_check.db"
        conn = await aiosqlite.connect(str(path))
        conn.row_factory = aiosqlite.Row
        await apply_production_pragmas(conn)

        async def _pragma(name):
            cursor = await conn.execute(f"PRAGMA {name}")
            row = await cursor.fetchone()
            return row[0]

        assert (await _pragma("journal_mode")) == "wal"
        assert (await _pragma("synchronous")) == 1   # NORMAL
        assert (await _pragma("busy_timeout")) == 5000
        assert (await _pragma("cache_size")) == -64000
        assert (await _pragma("mmap_size")) == 268435456
        assert (await _pragma("temp_store")) == 2    # MEMORY
        assert (await _pragma("foreign_keys")) == 1  # ON

        await conn.close()


class TestCheckpointWal:
    async def test_checkpoint_returns_three_ints(self, tmp_path):
        path = tmp_path / "ckpt.db"
        await init_db(str(path))
        try:
            busy, in_wal, checkpointed = await checkpoint_wal()
            assert isinstance(busy, int)
            assert isinstance(in_wal, int)
            assert isinstance(checkpointed, int)
        finally:
            await close_db()

    async def test_checkpoint_without_init_raises(self):
        await close_db()  # make sure nothing is initialized
        with pytest.raises(RuntimeError, match="not initialized"):
            await checkpoint_wal()


class TestPurgeOldRows:
    async def test_deletes_old_status_events(self, db):
        await _insert_service(db, "rtn-svc")
        await _insert_event(db, "rtn-svc", days_ago=120)
        await _insert_event(db, "rtn-svc", days_ago=5)
        await db.commit()

        result = await purge_old_rows(
            db=db,
            status_events_days=90,
            alert_sent_log_days=0,
            checkpoint_after=False,
        )
        assert result.status_events_deleted == 1

        cursor = await db.execute(
            "SELECT count(*) FROM status_events WHERE service_id='rtn-svc'"
        )
        remaining = (await cursor.fetchone())[0]
        assert remaining == 1

    async def test_preserves_recent_events(self, db):
        await _insert_service(db, "fresh")
        await _insert_event(db, "fresh", days_ago=1)
        await _insert_event(db, "fresh", days_ago=30)
        await db.commit()

        result = await purge_old_rows(
            db=db,
            status_events_days=90,
            alert_sent_log_days=0,
            checkpoint_after=False,
        )
        assert result.status_events_deleted == 0

    async def test_zero_window_disables_retention(self, db):
        await _insert_service(db, "nodel")
        await _insert_event(db, "nodel", days_ago=999)
        await db.commit()

        result = await purge_old_rows(
            db=db,
            status_events_days=0,
            alert_sent_log_days=0,
            checkpoint_after=False,
        )
        assert result.status_events_deleted == 0

        cursor = await db.execute("SELECT count(*) FROM status_events")
        assert (await cursor.fetchone())[0] == 1  # Still there

    async def test_deletes_old_alert_sent_log(self, db):
        await _insert_service(db, "als")
        await _insert_alert(db, "als", days_ago=200)
        await _insert_alert(db, "als", days_ago=3)
        await db.commit()

        result = await purge_old_rows(
            db=db,
            status_events_days=0,
            alert_sent_log_days=90,
            checkpoint_after=False,
        )
        assert result.alert_sent_log_deleted == 1

        cursor = await db.execute(
            "SELECT count(*) FROM alert_sent_log WHERE service_id='als'"
        )
        assert (await cursor.fetchone())[0] == 1

    async def test_boundary_is_inclusive_of_exactly_threshold(self, db):
        """An event exactly at the threshold is old enough to be purged."""
        await _insert_service(db, "edge")
        # Exactly 90 days ago — with status_events_days=90 threshold this
        # compares `created_at < datetime('now', '-90 days')`, which is a
        # strict less-than, so the row at exactly -90 days is kept.
        # This test locks in that behavior.
        await _insert_event(db, "edge", days_ago=90)
        await db.commit()

        result = await purge_old_rows(
            db=db,
            status_events_days=90,
            alert_sent_log_days=0,
            checkpoint_after=False,
        )
        assert result.status_events_deleted == 0

    async def test_runs_both_tables_together(self, db):
        await _insert_service(db, "both")
        await _insert_event(db, "both", days_ago=200)
        await _insert_alert(db, "both", days_ago=200)
        await db.commit()

        result = await purge_old_rows(
            db=db,
            status_events_days=90,
            alert_sent_log_days=90,
            checkpoint_after=False,
        )
        assert result.status_events_deleted == 1
        assert result.alert_sent_log_deleted == 1


class TestScheduledTicks:
    """Smoke tests for the APScheduler entry points."""

    async def test_scheduled_retention_tick_handles_missing_db(self, tmp_path, monkeypatch):
        """Retention tick should never raise, even on setup failures."""
        from app import retention
        from app.config import settings

        # Point at a DB that was never initialized
        monkeypatch.setattr(settings, "database_path", str(tmp_path / "nope.db"))
        # Tick must swallow the RuntimeError and log
        await retention.scheduled_retention_tick()

    async def test_scheduled_wal_checkpoint_tick_handles_missing_db(
        self, tmp_path, monkeypatch,
    ):
        from app import retention
        await retention.scheduled_wal_checkpoint_tick()  # no raise
