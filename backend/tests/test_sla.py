"""Unit tests for app.sla.compute_uptime."""

from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from app.config import settings
from app.database import run_migrations
from app.sla import WindowUptime, compute_uptime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SVC = "svc-a"

_CREATE_SVC = (
    "INSERT INTO services (id, display_name, category, poll_type, current_status) "
    "VALUES (?, 'Test Service', 'productivity', 'manual', 'unknown')"
)


async def _insert_event(
    conn: aiosqlite.Connection,
    *,
    service_id: str = _SVC,
    previous_status: str,
    new_status: str,
    created_at: datetime,
) -> None:
    await conn.execute(
        """INSERT INTO status_events
               (service_id, previous_status, new_status, source, created_at)
           VALUES (?, ?, ?, 'test', ?)""",
        (service_id, previous_status, new_status, created_at.isoformat()),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def conn(tmp_path):
    """In-memory DB with migrations applied and a single test service seeded."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys=ON")
    await run_migrations(db, settings.migrations_dir)
    await db.execute(_CREATE_SVC, (_SVC,))
    await db.commit()
    yield db
    await db.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComputeUptime:
    @pytest.mark.asyncio
    async def test_no_events_returns_none_uptime(self, conn):
        now = datetime.now(UTC)
        result = await compute_uptime(conn, _SVC, now - timedelta(hours=24), now)
        assert result == WindowUptime(
            operational_seconds=0.0,
            tracked_seconds=0.0,
            uptime_percent=None,
        )

    @pytest.mark.asyncio
    async def test_all_operational_window_returns_100(self, conn):
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=24)

        # Service went operational 1 hour before window_start (before window).
        await _insert_event(
            conn,
            previous_status="unknown",
            new_status="degraded",
            created_at=window_start - timedelta(hours=2),
        )
        await _insert_event(
            conn,
            previous_status="degraded",
            new_status="operational",
            created_at=window_start - timedelta(hours=1),
        )

        result = await compute_uptime(conn, _SVC, window_start, now)

        expected_seconds = (now - window_start).total_seconds()
        assert result.uptime_percent == 100.0
        assert abs(result.operational_seconds - expected_seconds) < 1.0
        assert abs(result.tracked_seconds - expected_seconds) < 1.0

    @pytest.mark.asyncio
    async def test_all_unknown_window_returns_none(self, conn):
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=24)

        await _insert_event(
            conn,
            previous_status="operational",
            new_status="unknown",
            created_at=window_start - timedelta(hours=1),
        )

        result = await compute_uptime(conn, _SVC, window_start, now)

        assert result.tracked_seconds == 0.0
        assert result.operational_seconds == 0.0
        assert result.uptime_percent is None

    @pytest.mark.asyncio
    async def test_mixed_statuses(self, conn):
        """Half operational, half degraded → uptime_percent == 50.0."""
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=4)
        midpoint = window_start + timedelta(hours=2)

        # Prime the service via a non-bootstrap transition before the window,
        # so the first in-window event isn't filtered by the unknown→operational
        # bootstrap rule.
        await _insert_event(
            conn,
            previous_status="degraded",
            new_status="operational",
            created_at=window_start - timedelta(minutes=1),
        )
        # degraded for last 2 h
        await _insert_event(
            conn,
            previous_status="operational",
            new_status="degraded",
            created_at=midpoint,
        )

        result = await compute_uptime(conn, _SVC, window_start, now)

        total_seconds = (now - window_start).total_seconds()
        expected_operational = (midpoint - window_start).total_seconds()
        assert abs(result.operational_seconds - expected_operational) < 1.0
        assert abs(result.tracked_seconds - total_seconds) < 1.0
        # uptime_percent ≈ 50 %
        assert result.uptime_percent is not None
        assert abs(result.uptime_percent - 50.0) < 0.1

    @pytest.mark.asyncio
    async def test_event_starts_before_window_clamps(self, conn):
        """Event starting 1h before the window, still active → full window tracked."""
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=6)
        # operational started 7h ago (1h before window_start) — use a non-bootstrap
        # transition so the event isn't filtered by the unknown→operational rule.
        await _insert_event(
            conn,
            previous_status="degraded",
            new_status="operational",
            created_at=window_start - timedelta(hours=1),
        )

        result = await compute_uptime(conn, _SVC, window_start, now)

        expected = (now - window_start).total_seconds()
        assert abs(result.tracked_seconds - expected) < 1.0
        assert result.uptime_percent == 100.0

    @pytest.mark.asyncio
    async def test_event_ends_after_window_clamps(self, conn):
        """Interval overlaps the end of the window — only in-window portion counts."""
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=2)
        # operational starts 1h into the window (non-bootstrap transition)
        event_start = window_start + timedelta(hours=1)
        await _insert_event(
            conn,
            previous_status="degraded",
            new_status="operational",
            created_at=event_start,
        )
        # No further event → interval extends to window_end (now).
        result = await compute_uptime(conn, _SVC, window_start, now)

        expected = (now - event_start).total_seconds()
        assert abs(result.operational_seconds - expected) < 1.0
        assert abs(result.tracked_seconds - expected) < 1.0
        assert result.uptime_percent == 100.0

    @pytest.mark.asyncio
    async def test_exact_boundary_event(self, conn):
        """Event created exactly at window_start is included."""
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=1)
        await _insert_event(
            conn,
            previous_status="degraded",
            new_status="operational",
            created_at=window_start,
        )

        result = await compute_uptime(conn, _SVC, window_start, now)

        expected = (now - window_start).total_seconds()
        assert abs(result.tracked_seconds - expected) < 1.0
        assert result.uptime_percent == 100.0

    @pytest.mark.asyncio
    async def test_ignores_unknown_to_operational_bootstrap(self, conn):
        """Bootstrap transition (prev=unknown, new=operational) is excluded."""
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=2)

        # This is the bootstrap event — should be excluded entirely.
        await _insert_event(
            conn,
            previous_status="unknown",
            new_status="operational",
            created_at=window_start - timedelta(hours=1),
        )
        # Degraded after bootstrap — should be tracked.
        await _insert_event(
            conn,
            previous_status="operational",
            new_status="degraded",
            created_at=window_start,
        )

        result = await compute_uptime(conn, _SVC, window_start, now)

        # Only the degraded interval is tracked; no operational seconds.
        expected_tracked = (now - window_start).total_seconds()
        assert abs(result.tracked_seconds - expected_tracked) < 1.0
        assert result.operational_seconds == 0.0
        assert result.uptime_percent == 0.0

    @pytest.mark.asyncio
    async def test_unknown_interval_excluded_from_tracked(self, conn):
        """unknown intervals don't count as downtime — uptime_percent is 100.

        Window: 4h
          - operational: first 2h
          - unknown:     last 2h
        tracked_seconds ≈ 2h (only operational portion)
        uptime_percent  = 100.0
        """
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=4)
        midpoint = window_start + timedelta(hours=2)

        await _insert_event(
            conn,
            previous_status="degraded",
            new_status="operational",
            created_at=window_start,
        )
        await _insert_event(
            conn,
            previous_status="operational",
            new_status="unknown",
            created_at=midpoint,
        )

        result = await compute_uptime(conn, _SVC, window_start, now)

        expected_tracked = (midpoint - window_start).total_seconds()
        assert abs(result.tracked_seconds - expected_tracked) < 1.0
        assert abs(result.operational_seconds - expected_tracked) < 1.0
        assert result.uptime_percent == 100.0
