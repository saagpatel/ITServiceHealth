"""Tests for the multi-burn-rate SLO alerting pipeline.

Covers:
- BurnRateMath: evaluate_burn_rate edge cases and math correctness
- Routing: route_slo_burn_rate_alert suppression rules
- RecordAlert: record_slo_alert DB writes
- SlackBuilder: build_slo_burn_rate_alert Block Kit payload
- Cycle: run_slo_burn_rate_cycle guard + happy path
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import aiosqlite
import pytest

from app.alerting import burn_rate as br_module
from app.alerting.burn_rate import BurnRateBreach, evaluate_burn_rate, run_slo_burn_rate_cycle
from app.alerting.routing import (
    build_slo_burn_rate_dedup_key,
    record_slo_alert,
    route_slo_burn_rate_alert,
)
from app.alerting.slack import build_slo_burn_rate_alert
from app.config import settings
from app.database import run_migrations
from app.sla import WindowUptime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SVC = "test_svc"
_SVC_NAME = "Test Service"

_CREATE_SVC = (
    "INSERT INTO services (id, display_name, category, poll_type, current_status) "
    "VALUES (?, ?, 'productivity', 'manual', 'operational')"
)


async def _seed_service(db: aiosqlite.Connection, service_id: str = _SVC, name: str = _SVC_NAME) -> None:
    await db.execute(_CREATE_SVC, (service_id, name))
    await db.commit()


async def _insert_event(
    db: aiosqlite.Connection,
    *,
    service_id: str = _SVC,
    previous_status: str,
    new_status: str,
    created_at: datetime,
) -> None:
    await db.execute(
        """INSERT INTO status_events
               (service_id, previous_status, new_status, source, created_at)
           VALUES (?, ?, ?, 'test', ?)""",
        (service_id, previous_status, new_status, created_at.isoformat()),
    )
    await db.commit()


def _make_fast_breach(
    service_id: str = _SVC,
    service_name: str = _SVC_NAME,
    long_br: float = 20.0,
    short_br: float = 22.0,
    budget_remaining: float = 60.0,
) -> BurnRateBreach:
    return BurnRateBreach(
        service_id=service_id,
        service_name=service_name,
        severity="fast",
        long_window_burn_rate=long_br,
        short_window_burn_rate=short_br,
        error_budget_remaining_pct=budget_remaining,
        long_window_label="1h",
        short_window_label="5m",
    )


def _make_slow_breach(
    service_id: str = _SVC,
    service_name: str = _SVC_NAME,
    long_br: float = 8.0,
    short_br: float = 9.0,
    budget_remaining: float = 80.0,
) -> BurnRateBreach:
    return BurnRateBreach(
        service_id=service_id,
        service_name=service_name,
        severity="slow",
        long_window_burn_rate=long_br,
        short_window_burn_rate=short_br,
        error_budget_remaining_pct=budget_remaining,
        long_window_label="6h",
        short_window_label="30m",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    """In-memory DB with migrations applied."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(conn, settings.migrations_dir)
    yield conn
    await conn.close()


@pytest.fixture
async def db_with_svc(db: aiosqlite.Connection):
    """In-memory DB seeded with a single service."""
    await _seed_service(db)
    yield db


# ---------------------------------------------------------------------------
# Helper: stub compute_uptime with a window-size → uptime_percent map
# ---------------------------------------------------------------------------


def _stub_compute_uptime(
    monkeypatch: pytest.MonkeyPatch,
    window_to_uptime: dict[timedelta, float | None],
) -> None:
    """Replace compute_uptime in the burn_rate module so each (end - start) lookup
    returns a pre-set WindowUptime. Layering seed events per-window produces
    overlapping history that can't represent independent per-window uptimes —
    stubbing compute_uptime is the clean way to unit-test the math."""

    async def _fake(
        db: aiosqlite.Connection,
        service_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> WindowUptime:
        window = window_end - window_start
        for ws, pct in window_to_uptime.items():
            if abs((window - ws).total_seconds()) < 2.0:
                if pct is None:
                    return WindowUptime(operational_seconds=0.0, tracked_seconds=0.0, uptime_percent=None)
                total = ws.total_seconds()
                op = total * (pct / 100.0)
                return WindowUptime(operational_seconds=op, tracked_seconds=total, uptime_percent=pct)
        return WindowUptime(operational_seconds=0.0, tracked_seconds=0.0, uptime_percent=None)

    monkeypatch.setattr(br_module, "compute_uptime", _fake)


# ---------------------------------------------------------------------------
# Helper: seed status events for a given uptime in a window
# ---------------------------------------------------------------------------


async def _seed_constant_uptime(
    db: aiosqlite.Connection,
    service_id: str,
    now: datetime,
    window_size: timedelta,
    uptime_pct: float,
) -> None:
    """Insert events so compute_uptime returns ~uptime_pct over [now-window, now].

    Seeds one non-bootstrap degraded→operational event right before the window
    starts (so the window opens already operational), then optionally inserts a
    degraded event partway into the window to reduce uptime below 100%.
    """
    window_start = now - window_size
    total_seconds = window_size.total_seconds()

    # Start window in operational state (non-bootstrap transition so it isn't filtered)
    await _insert_event(
        db,
        service_id=service_id,
        previous_status="degraded",
        new_status="operational",
        created_at=window_start - timedelta(seconds=5),
    )

    if uptime_pct < 100.0:
        # Insert a degraded event at the fraction-point so that operational
        # portion == uptime_pct % and degraded portion == (100 - uptime_pct) %
        operational_fraction = uptime_pct / 100.0
        degraded_start = window_start + timedelta(seconds=total_seconds * operational_fraction)
        await _insert_event(
            db,
            service_id=service_id,
            previous_status="operational",
            new_status="degraded",
            created_at=degraded_start,
        )


# ---------------------------------------------------------------------------
# TestBurnRateMath
# ---------------------------------------------------------------------------


class TestBurnRateMath:
    @pytest.mark.asyncio
    async def test_burn_rate_zero_downtime_returns_zero(self, db_with_svc: aiosqlite.Connection):
        """100% uptime across all windows → no breaches."""
        now = datetime.now(UTC)
        db = db_with_svc

        # Seed a single operational event well before all windows
        await _insert_event(
            db,
            previous_status="degraded",
            new_status="operational",
            created_at=now - timedelta(days=31),
        )

        breaches = await evaluate_burn_rate(db, _SVC, _SVC_NAME, now)
        assert breaches == []

    @pytest.mark.asyncio
    async def test_burn_rate_math_matches_hand_calc(
        self, db_with_svc: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch,
    ):
        """97.12% uptime -> 2.88% failure rate -> 28.8x burn at 99.9% SLO -> fast breach."""
        _stub_compute_uptime(monkeypatch, {
            timedelta(minutes=5):  97.12,
            timedelta(minutes=30): 100.0,
            timedelta(hours=1):    97.12,
            timedelta(hours=6):    100.0,
            timedelta(days=30):    99.95,
        })
        breaches = await evaluate_burn_rate(db_with_svc, _SVC, _SVC_NAME, datetime.now(UTC))

        fast_breaches = [b for b in breaches if b.severity == "fast"]
        assert len(fast_breaches) == 1
        b = fast_breaches[0]
        assert abs(b.long_window_burn_rate - 28.8) < 0.5
        assert abs(b.short_window_burn_rate - 28.8) < 0.5

    @pytest.mark.asyncio
    async def test_fast_breach_requires_both_windows(
        self, db_with_svc: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch,
    ):
        """5m high burn but 1h low burn -> no fast breach."""
        _stub_compute_uptime(monkeypatch, {
            timedelta(minutes=5):  97.0,  # ~30x burn
            timedelta(minutes=30): 100.0,
            timedelta(hours=1):    99.5,  # ~5x burn, below 14.4 fast threshold
            timedelta(hours=6):    100.0,
            timedelta(days=30):    100.0,
        })
        breaches = await evaluate_burn_rate(db_with_svc, _SVC, _SVC_NAME, datetime.now(UTC))
        assert [b for b in breaches if b.severity == "fast"] == []

    @pytest.mark.asyncio
    async def test_slow_breach_requires_both_windows(
        self, db_with_svc: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch,
    ):
        """30m high burn but 6h low burn -> no slow breach."""
        _stub_compute_uptime(monkeypatch, {
            timedelta(minutes=5):  100.0,
            timedelta(minutes=30): 99.0,  # 10x burn
            timedelta(hours=1):    100.0,
            timedelta(hours=6):    99.8,  # 2x burn, below 6.0 slow threshold
            timedelta(days=30):    100.0,
        })
        breaches = await evaluate_burn_rate(db_with_svc, _SVC, _SVC_NAME, datetime.now(UTC))
        assert [b for b in breaches if b.severity == "slow"] == []

    @pytest.mark.asyncio
    async def test_unknown_dominated_window_does_not_alert(self, db: aiosqlite.Connection):
        """No events in any window → compute_uptime returns None → no breach."""
        now = datetime.now(UTC)
        await _seed_service(db)

        # Insert only an 'unknown' event — no non-unknown data in any window
        await _insert_event(
            db,
            previous_status="operational",
            new_status="unknown",
            created_at=now - timedelta(days=31),
        )

        breaches = await evaluate_burn_rate(db, _SVC, _SVC_NAME, now)
        assert breaches == [], "Must not page on windows with no tracked data"

    @pytest.mark.asyncio
    async def test_both_fast_and_slow_can_fire_simultaneously(
        self, db_with_svc: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch,
    ):
        """All four windows at high burn -> 2 breaches returned (fast + slow)."""
        _stub_compute_uptime(monkeypatch, {
            timedelta(minutes=5):  97.0,
            timedelta(minutes=30): 97.0,
            timedelta(hours=1):    97.0,
            timedelta(hours=6):    97.0,
            timedelta(days=30):    99.95,
        })
        breaches = await evaluate_burn_rate(db_with_svc, _SVC, _SVC_NAME, datetime.now(UTC))
        severities = {b.severity for b in breaches}
        assert "fast" in severities
        assert "slow" in severities
        assert len(breaches) == 2

    @pytest.mark.asyncio
    async def test_error_budget_remaining_pct_from_30d_uptime(
        self, db_with_svc: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch,
    ):
        """30d uptime of 99.95% -> half budget used -> ~50% remaining."""
        _stub_compute_uptime(monkeypatch, {
            timedelta(minutes=5):  97.0,
            timedelta(minutes=30): 97.0,
            timedelta(hours=1):    97.0,
            timedelta(hours=6):    97.0,
            timedelta(days=30):    99.95,
        })
        breaches = await evaluate_burn_rate(db_with_svc, _SVC, _SVC_NAME, datetime.now(UTC))
        fast = next(b for b in breaches if b.severity == "fast")
        assert abs(fast.error_budget_remaining_pct - 50.0) < 2.0

    @pytest.mark.asyncio
    async def test_error_budget_remaining_pct_fully_consumed(
        self, db_with_svc: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch,
    ):
        """30d uptime exactly at 99.9% target -> 0% budget remaining."""
        _stub_compute_uptime(monkeypatch, {
            timedelta(minutes=5):  97.0,
            timedelta(minutes=30): 97.0,
            timedelta(hours=1):    97.0,
            timedelta(hours=6):    97.0,
            timedelta(days=30):    99.9,
        })
        breaches = await evaluate_burn_rate(db_with_svc, _SVC, _SVC_NAME, datetime.now(UTC))
        fast = next(b for b in breaches if b.severity == "fast")
        assert fast.error_budget_remaining_pct <= 1.0

    @pytest.mark.asyncio
    async def test_error_budget_remaining_pct_full_when_no_data(
        self, db_with_svc: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch,
    ):
        """30d window with no tracked data (uptime_percent=None) -> 100% remaining."""
        _stub_compute_uptime(monkeypatch, {
            timedelta(minutes=5):  97.0,
            timedelta(minutes=30): 97.0,
            timedelta(hours=1):    97.0,
            timedelta(hours=6):    97.0,
            timedelta(days=30):    None,
        })
        breaches = await evaluate_burn_rate(db_with_svc, _SVC, _SVC_NAME, datetime.now(UTC))
        fast = next(b for b in breaches if b.severity == "fast")
        assert fast.error_budget_remaining_pct == 100.0


# ---------------------------------------------------------------------------
# TestRouting
# ---------------------------------------------------------------------------


class TestRouting:
    @pytest.mark.asyncio
    async def test_route_sends_when_clean(self, db_with_svc: aiosqlite.Connection, monkeypatch):
        """No prior alerts, no maintenance, webhook set → should_send=True."""
        monkeypatch.setattr(settings, "slack_webhook_url", "https://hooks.slack.com/test")
        monkeypatch.setattr(settings, "slo_burn_rate_enabled", True)

        breach = _make_fast_breach()
        now = datetime.now(UTC)

        decision = await route_slo_burn_rate_alert(
            db_with_svc, breach, "https://hooks.slack.com/test", now
        )

        assert decision.should_send is True
        assert decision.dedup_key == "slo_burn:test_svc:fast"
        assert decision.channel_mention == "<!here>"
        assert decision.suppressed_by is None

    @pytest.mark.asyncio
    async def test_route_slow_has_no_channel_mention(self, db_with_svc: aiosqlite.Connection):
        """severity=slow → channel_mention is None (no @here)."""
        breach = _make_slow_breach()
        now = datetime.now(UTC)

        decision = await route_slo_burn_rate_alert(
            db_with_svc, breach, "https://hooks.slack.com/test", now
        )

        assert decision.should_send is True
        assert decision.channel_mention is None

    @pytest.mark.asyncio
    async def test_route_suppressed_by_dedup(self, db_with_svc: aiosqlite.Connection):
        """Existing unsuppressed alert_sent_log row → should_send=False, suppressed_by='dedup'."""
        db = db_with_svc
        breach = _make_fast_breach()
        dedup_key = build_slo_burn_rate_dedup_key(breach.service_id, breach.severity)
        now = datetime.now(UTC)

        # Write a recent unsuppressed row
        await db.execute(
            """INSERT INTO alert_sent_log
               (dedup_key, service_id, status_event_id, severity, new_status,
                alert_kind, slack_channel, slack_ts, suppressed_by,
                first_sent_at, last_updated_at)
               VALUES (?, ?, NULL, 'critical', 'slo_fast_burn', 'slo_burn_rate',
                       NULL, NULL, NULL,
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (dedup_key, breach.service_id),
        )
        await db.commit()

        decision = await route_slo_burn_rate_alert(
            db, breach, "https://hooks.slack.com/test", now
        )

        assert decision.should_send is False
        assert decision.suppressed_by == "dedup"

    @pytest.mark.asyncio
    async def test_route_suppressed_by_maintenance(self, db_with_svc: aiosqlite.Connection):
        """Active maintenance window → should_send=False, suppressed_by='maintenance_window'."""
        db = db_with_svc
        breach = _make_fast_breach()
        now = datetime.now(UTC)

        # Insert a maintenance window active right now
        await db.execute(
            """INSERT INTO scheduled_maintenances
               (service_id, title, status, scheduled_for, scheduled_until)
               VALUES (?, 'Test maintenance', 'in_progress',
                       datetime('now', '-1 hour'), datetime('now', '+1 hour'))""",
            (breach.service_id,),
        )
        await db.commit()

        decision = await route_slo_burn_rate_alert(
            db, breach, "https://hooks.slack.com/test", now
        )

        assert decision.should_send is False
        assert decision.suppressed_by == "maintenance_window"

    @pytest.mark.asyncio
    async def test_route_suppressed_when_no_webhook(self, db_with_svc: aiosqlite.Connection):
        """webhook_url=None → should_send=False, suppressed_by='webhook_not_configured'."""
        breach = _make_fast_breach()
        now = datetime.now(UTC)

        decision = await route_slo_burn_rate_alert(
            db_with_svc, breach, None, now
        )

        assert decision.should_send is False
        assert decision.suppressed_by == "webhook_not_configured"

    def test_build_dedup_key_format(self):
        """build_slo_burn_rate_dedup_key produces expected format."""
        assert build_slo_burn_rate_dedup_key("slack_api", "fast") == "slo_burn:slack_api:fast"
        assert build_slo_burn_rate_dedup_key("github", "slow") == "slo_burn:github:slow"


# ---------------------------------------------------------------------------
# TestRecordAlert
# ---------------------------------------------------------------------------


class TestRecordAlert:
    @pytest.mark.asyncio
    async def test_record_alert_writes_row(self, db_with_svc: aiosqlite.Connection):
        """record_slo_alert with should_send=True writes a row with suppressed_by IS NULL."""
        db = db_with_svc
        breach = _make_fast_breach()
        dedup_key = build_slo_burn_rate_dedup_key(breach.service_id, breach.severity)

        from app.alerting.routing import RoutingDecision
        decision = RoutingDecision(
            should_send=True,
            webhook_url="https://hooks.slack.com/test",
            channel_mention="<!here>",
            dedup_key=dedup_key,
            tier="critical",
            suppressed_by=None,
        )

        await record_slo_alert(db, breach, decision)
        await db.commit()

        cursor = await db.execute(
            "SELECT * FROM alert_sent_log WHERE dedup_key = ?", (dedup_key,)
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["alert_kind"] == "slo_burn_rate"
        assert row["dedup_key"] == dedup_key
        assert row["service_id"] == breach.service_id
        assert row["suppressed_by"] is None

    @pytest.mark.asyncio
    async def test_record_alert_records_suppression(self, db_with_svc: aiosqlite.Connection):
        """record_slo_alert with suppressed_by='dedup' writes that reason to the row."""
        db = db_with_svc
        breach = _make_slow_breach()
        dedup_key = build_slo_burn_rate_dedup_key(breach.service_id, breach.severity)

        from app.alerting.routing import RoutingDecision
        decision = RoutingDecision(
            should_send=False,
            webhook_url=None,
            channel_mention=None,
            dedup_key=dedup_key,
            tier="important",
            suppressed_by="dedup",
        )

        await record_slo_alert(db, breach, decision)
        await db.commit()

        cursor = await db.execute(
            "SELECT suppressed_by FROM alert_sent_log WHERE dedup_key = ?", (dedup_key,)
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["suppressed_by"] == "dedup"


# ---------------------------------------------------------------------------
# TestSlackBuilder
# ---------------------------------------------------------------------------


def _payload_text(payload: dict[str, Any]) -> str:
    """Flatten all text values in the payload blocks into a single string."""
    parts: list[str] = [payload.get("text", "")]
    for block in payload.get("blocks", []):
        t = block.get("text", {})
        if isinstance(t, dict):
            parts.append(t.get("text", ""))
        for field in block.get("fields", []):
            parts.append(field.get("text", ""))
        for elem in block.get("elements", []):
            if isinstance(elem, dict):
                et = elem.get("text", {})
                if isinstance(et, dict):
                    parts.append(et.get("text", ""))
                else:
                    parts.append(str(et))
    return "\n".join(parts)


class TestSlackBuilder:
    def test_payload_includes_severity_and_target(self):
        """Fast breach payload mentions 'Fast' and '99.9%' and the burn-rate number."""
        breach = _make_fast_breach(long_br=20.0)
        payload = build_slo_burn_rate_alert(
            breach, channel_mention="", dedup_key=None, status_page_url=None
        )

        text = _payload_text(payload)
        assert "Fast" in text, "Expected severity label 'Fast' in payload"
        assert "99.9" in text, "Expected SLO target in payload"
        assert "20.0" in text, "Expected long-window burn rate in payload"

    def test_payload_includes_ack_button_when_enabled(self, monkeypatch):
        """slack_ack_enabled=True + dedup_key → actions block with ack_alert button."""
        monkeypatch.setattr(settings, "slack_ack_enabled", True)
        breach = _make_fast_breach()
        dedup_key = "slo_burn:test_svc:fast"

        payload = build_slo_burn_rate_alert(
            breach, channel_mention="", dedup_key=dedup_key, status_page_url=None
        )

        action_ids = [
            elem.get("action_id")
            for block in payload.get("blocks", [])
            if block.get("type") == "actions"
            for elem in block.get("elements", [])
        ]
        assert "ack_alert" in action_ids, "Expected ack_alert button when ack enabled"

        # Verify value equals dedup_key
        for block in payload.get("blocks", []):
            if block.get("type") == "actions":
                for elem in block.get("elements", []):
                    if elem.get("action_id") == "ack_alert":
                        assert elem.get("value") == dedup_key

    def test_payload_omits_ack_button_when_disabled(self, monkeypatch):
        """slack_ack_enabled=False → no ack_alert action in payload."""
        monkeypatch.setattr(settings, "slack_ack_enabled", False)
        breach = _make_fast_breach()

        payload = build_slo_burn_rate_alert(
            breach,
            channel_mention="",
            dedup_key="slo_burn:test_svc:fast",
            status_page_url=None,
        )

        action_ids = [
            elem.get("action_id")
            for block in payload.get("blocks", [])
            if block.get("type") == "actions"
            for elem in block.get("elements", [])
        ]
        assert "ack_alert" not in action_ids, "ack_alert must not appear when disabled"

    def test_payload_includes_view_status_button_when_url_provided(self, monkeypatch):
        """status_page_url provided → payload has a button with that URL."""
        monkeypatch.setattr(settings, "slack_ack_enabled", False)
        breach = _make_fast_breach()
        url = "https://status.example.com"

        payload = build_slo_burn_rate_alert(
            breach, channel_mention="", dedup_key=None, status_page_url=url
        )

        urls_in_payload = [
            elem.get("url")
            for block in payload.get("blocks", [])
            if block.get("type") == "actions"
            for elem in block.get("elements", [])
        ]
        assert url in urls_in_payload, f"Expected URL {url} in action buttons"

    def test_payload_channel_mention_appears_for_fast(self, monkeypatch):
        """channel_mention='<!here>' → that string is present in the payload."""
        monkeypatch.setattr(settings, "slack_ack_enabled", False)
        breach = _make_fast_breach()

        payload = build_slo_burn_rate_alert(
            breach, channel_mention="<!here>", dedup_key=None, status_page_url=None
        )

        text = _payload_text(payload)
        assert "<!here>" in text, "Expected <!here> in payload for fast breach"

    def test_payload_omits_channel_mention_context_when_empty(self, monkeypatch):
        """channel_mention='' → no context block emitted for the mention."""
        monkeypatch.setattr(settings, "slack_ack_enabled", False)
        breach = _make_slow_breach()

        payload = build_slo_burn_rate_alert(
            breach, channel_mention="", dedup_key=None, status_page_url=None
        )

        # The mention context block is only appended when channel_mention is truthy
        mention_contexts = [
            block for block in payload.get("blocks", [])
            if block.get("type") == "context"
            and any("here" in str(e) for e in block.get("elements", []))
        ]
        assert mention_contexts == [], "No <!here> context block should be emitted for slow breach"


# ---------------------------------------------------------------------------
# TestCycle
# ---------------------------------------------------------------------------


class TestCycle:
    @pytest.mark.asyncio
    async def test_cycle_noops_when_disabled(self, monkeypatch):
        """slo_burn_rate_enabled=False → run_slo_burn_rate_cycle returns immediately."""
        monkeypatch.setattr(settings, "slo_burn_rate_enabled", False)

        called: list[bool] = []

        async def _spy(*args: Any, **kwargs: Any) -> list:
            called.append(True)
            return []

        monkeypatch.setattr(
            "app.alerting.burn_rate.evaluate_burn_rate", _spy
        )

        app_mock = MagicMock()
        await run_slo_burn_rate_cycle(app_mock)

        assert called == [], "evaluate_burn_rate must not be called when disabled"

    @pytest.mark.asyncio
    async def test_cycle_routes_and_records_for_each_breach(
        self, db_with_svc: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch,
    ):
        """Enable flag, stub a fast breach, mock Slack send → alert_sent_log row written."""
        monkeypatch.setattr(settings, "slo_burn_rate_enabled", True)
        monkeypatch.setattr(settings, "slack_webhook_url", "https://hooks.slack.com/fake")

        db = db_with_svc

        # Stub evaluate_burn_rate to return a fast breach for our seeded service.
        async def _fake_evaluate(
            _db: aiosqlite.Connection,
            service_id: str,
            service_name: str,
            _now: datetime,
        ) -> list[BurnRateBreach]:
            return [_make_fast_breach(service_id=service_id, service_name=service_name)]

        monkeypatch.setattr(br_module, "evaluate_burn_rate", _fake_evaluate)

        # get_db is imported lazily inside run_slo_burn_rate_cycle — patch at source.
        async def _fake_get_db() -> aiosqlite.Connection:
            return db
        monkeypatch.setattr("app.database.get_db", _fake_get_db)

        # Patch the Slack send hook wherever burn_rate.py imports it from.
        send_calls: list[dict[str, Any]] = []

        async def _fake_send(*args: Any, **kwargs: Any) -> bool:
            # Accept both positional (url, payload) and kwargs; store the payload.
            payload = kwargs.get("payload") or (args[1] if len(args) > 1 else None)
            if isinstance(payload, dict):
                send_calls.append(payload)
            return True
        # Try common names; set whichever exists on the module.
        for attr in ("send_slack_alert", "send_slack_webhook", "send_slack"):
            if hasattr(br_module, attr):
                monkeypatch.setattr(br_module, attr, _fake_send)

        app_mock = MagicMock()
        await run_slo_burn_rate_cycle(app_mock)

        cursor = await db.execute(
            "SELECT alert_kind, dedup_key, suppressed_by FROM alert_sent_log "
            "WHERE alert_kind = 'slo_burn_rate'"
        )
        rows = await cursor.fetchall()
        assert len(rows) >= 1, "Expected at least one slo_burn_rate row in alert_sent_log"

    @pytest.mark.asyncio
    async def test_cycle_logs_duration_no_error(
        self, db_with_svc: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch,
    ):
        """Cycle completes without raising even when no breaches fire."""
        monkeypatch.setattr(settings, "slo_burn_rate_enabled", True)
        monkeypatch.setattr(settings, "slack_webhook_url", None)

        db = db_with_svc

        async def _fake_get_db() -> aiosqlite.Connection:
            return db
        monkeypatch.setattr("app.database.get_db", _fake_get_db)

        # No breaches so no Slack send path is exercised.
        async def _no_breaches(
            _db: aiosqlite.Connection, _sid: str, _sname: str, _now: datetime,
        ) -> list[BurnRateBreach]:
            return []
        monkeypatch.setattr(br_module, "evaluate_burn_rate", _no_breaches)

        app_mock = MagicMock()
        await run_slo_burn_rate_cycle(app_mock)  # must not raise
