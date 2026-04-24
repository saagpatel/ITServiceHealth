"""Tests for postmortems.py (render_markdown, write_postmortem) and the
alerting engine integration that calls write_postmortem on service recovery.
"""

import asyncio
import hashlib
from datetime import UTC, datetime

import pytest
import yaml

from app.alerting.engine import process_changes
from app.poller.change_detector import StatusChange
from app.postmortems import render_markdown, write_postmortem

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

_BASE_EVENTS = [
    {
        "id": 1,
        "service_id": "okta",
        "previous_status": "operational",
        "new_status": "degraded",
        "vendor_title": "Elevated error rates",
        "vendor_detail": "Users experiencing login failures",
        "impact_statement": "Okta is degraded",
        "source": "statuspage_json",
        "created_at": "2026-04-24T10:00:00Z",
    },
    {
        "id": 2,
        "service_id": "okta",
        "previous_status": "degraded",
        "new_status": "major_outage",
        "vendor_title": "Complete SSO failure",
        "vendor_detail": None,
        "impact_statement": None,
        "source": "statuspage_json",
        "created_at": "2026-04-24T10:15:00Z",
    },
    {
        "id": 3,
        "service_id": "okta",
        "previous_status": "major_outage",
        "new_status": "operational",
        "vendor_title": None,
        "vendor_detail": None,
        "impact_statement": "Okta has recovered",
        "source": "statuspage_json",
        "created_at": "2026-04-24T11:00:00Z",
    },
]


def _sample_report(**overrides) -> dict:
    """Return a realistic report dict with all required keys."""
    base = {
        "service_id": "okta",
        "service_name": "Okta",
        "started_at": "2026-04-24T10:00:00Z",
        "resolved_at": "2026-04-24T11:00:00Z",
        "duration_seconds": 3600,
        "duration_human": "1h",
        "peak_severity": "major_outage",
        "affected_downstream": ["Box Web", "Box Mobile"],
        "event_count": 3,
        "events": list(_BASE_EVENTS),
        "impact_summary": "Okta experienced major outage for 1h.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# TestRenderMarkdown — pure function, no I/O
# ---------------------------------------------------------------------------


class TestRenderMarkdown:
    def test_render_includes_all_eight_sections_in_order(self):
        md = render_markdown(_sample_report())
        expected_sections = [
            "## Summary",
            "## Impact",
            "## Root Cause",
            "## Timeline",
            "## What Went Well",
            "## What Went Poorly",
            "## What Got Lucky",
            "## Action Items",
        ]
        positions = [md.index(s) for s in expected_sections]
        assert positions == sorted(positions), (
            "Sections are not in the expected order"
        )

    def test_render_auto_fills_summary_with_impact_summary(self):
        report = _sample_report(impact_summary="Okta was down for exactly 1h.")
        md = render_markdown(report)
        summary_start = md.index("## Summary")
        impact_start = md.index("## Impact")
        summary_body = md[summary_start:impact_start]
        assert "Okta was down for exactly 1h." in summary_body

    def test_render_impact_lists_peak_severity_duration_count_affected(self):
        report = _sample_report(
            peak_severity="major_outage",
            duration_human="1h",
            event_count=3,
            affected_downstream=["Box Web", "Box Mobile"],
        )
        md = render_markdown(report)
        impact_start = md.index("## Impact")
        root_cause_start = md.index("## Root Cause")
        impact_body = md[impact_start:root_cause_start]

        assert "major_outage" in impact_body
        assert "1h" in impact_body
        assert "3" in impact_body
        assert "Box Web" in impact_body
        assert "Box Mobile" in impact_body

    def test_render_impact_handles_empty_affected_downstream(self):
        report = _sample_report(affected_downstream=[])
        md = render_markdown(report)
        impact_start = md.index("## Impact")
        root_cause_start = md.index("## Root Cause")
        impact_body = md[impact_start:root_cause_start]
        assert "None" in impact_body

    def test_render_timeline_renders_events_chronologically(self):
        md = render_markdown(_sample_report())
        timeline_start = md.index("## Timeline")
        well_start = md.index("## What Went Well")
        timeline_body = md[timeline_start:well_start]

        bullets = [line for line in timeline_body.splitlines() if line.startswith("- ")]
        assert len(bullets) == 3

        import re
        time_pattern = re.compile(r"\d{2}:\d{2}:\d{2} UTC")
        arrow_pattern = re.compile(r"\w+ → \w+")
        for bullet in bullets:
            assert time_pattern.search(bullet), f"No HH:MM:SS UTC in: {bullet!r}"
            assert arrow_pattern.search(bullet), f"No arrow in: {bullet!r}"

    def test_render_timeline_handles_no_events(self):
        report = _sample_report(events=[])
        md = render_markdown(report)
        timeline_start = md.index("## Timeline")
        well_start = md.index("## What Went Well")
        timeline_body = md[timeline_start:well_start]
        assert "_No events recorded._" in timeline_body

    def test_render_timeline_handles_missing_events_key(self):
        report = _sample_report()
        del report["events"]
        md = render_markdown(report)
        timeline_start = md.index("## Timeline")
        well_start = md.index("## What Went Well")
        timeline_body = md[timeline_start:well_start]
        assert "_No events recorded._" in timeline_body

    def test_render_timeline_prefers_vendor_title_over_detail_and_impact(self):
        event_all = {
            "previous_status": "operational",
            "new_status": "degraded",
            "vendor_title": "THE TITLE",
            "vendor_detail": "the detail",
            "impact_statement": "the impact",
            "created_at": "2026-04-24T10:00:00Z",
        }
        md_all = render_markdown(_sample_report(events=[event_all]))
        timeline_start = md_all.index("## Timeline")
        well_start = md_all.index("## What Went Well")
        body_all = md_all[timeline_start:well_start]
        assert "THE TITLE" in body_all
        assert "the detail" not in body_all
        assert "the impact" not in body_all

        # vendor_detail fallback (no vendor_title)
        event_detail = dict(event_all, vendor_title=None)
        md_detail = render_markdown(_sample_report(events=[event_detail]))
        body_detail = md_detail[md_detail.index("## Timeline"):md_detail.index("## What Went Well")]
        assert "the detail" in body_detail

        # impact_statement fallback (no vendor_title, no vendor_detail)
        event_impact = dict(event_all, vendor_title=None, vendor_detail=None)
        md_impact = render_markdown(_sample_report(events=[event_impact]))
        body_impact = md_impact[md_impact.index("## Timeline"):md_impact.index("## What Went Well")]
        assert "the impact" in body_impact

    def test_render_preserves_all_todo_placeholders(self):
        md = render_markdown(_sample_report())
        assert "_TODO: Describe the root cause._" in md
        assert "_TODO: What held up during this incident?_" in md
        assert "_TODO: Where did the response fall short?_" in md
        assert "_TODO: What could have been worse but wasn't?_" in md
        assert "_TODO: How do we stop this class of incident from recurring?_" in md
        assert "_TODO: How do we reduce impact next time?_" in md
        assert "_TODO: How do we see it sooner?_" in md
        assert "_TODO: What follow-up repairs or backfills are needed?_" in md

    def test_render_frontmatter_is_valid_yaml(self):
        md = render_markdown(_sample_report())
        # Extract text between the two "---" delimiters
        lines = md.splitlines()
        assert lines[0] == "---"
        end_idx = lines.index("---", 1)
        frontmatter_text = "\n".join(lines[1:end_idx])
        fm = yaml.safe_load(frontmatter_text)
        assert isinstance(fm, dict)
        required_keys = {
            "service", "service_name", "started_at", "resolved_at",
            "duration", "peak_severity", "affected_downstream",
            "event_count", "status",
        }
        assert required_keys <= fm.keys()
        assert fm["status"] == "draft"

    def test_render_frontmatter_escapes_yaml_special_chars(self):
        # Service name with a colon — yaml.safe_dump must quote it properly
        report = _sample_report(service_name="Okta: identity", service_id="okta-identity")
        md = render_markdown(report)
        lines = md.splitlines()
        assert lines[0] == "---"
        end_idx = lines.index("---", 1)
        frontmatter_text = "\n".join(lines[1:end_idx])
        fm = yaml.safe_load(frontmatter_text)
        assert fm["service_name"] == "Okta: identity"

        # Service name with a leading dash
        report2 = _sample_report(service_name="- Okta primary", service_id="okta2")
        md2 = render_markdown(report2)
        lines2 = md2.splitlines()
        end_idx2 = lines2.index("---", 1)
        fm2 = yaml.safe_load("\n".join(lines2[1:end_idx2]))
        assert fm2["service_name"] == "- Okta primary"


# ---------------------------------------------------------------------------
# TestWritePostmortem — async I/O, uses tmp_path
# ---------------------------------------------------------------------------


class TestWritePostmortem:
    @pytest.mark.asyncio
    async def test_write_creates_file_with_expected_filename(self, tmp_path):
        report = _sample_report()
        result = await write_postmortem(report, out_dir=tmp_path)
        assert result is not None
        assert result.exists()

        # Verify filename format: {service_id}-{compact_ts}-{6_char_sha}.md
        started_at = report["started_at"]
        resolved_at = report["resolved_at"]
        sha = hashlib.sha1(
            f"{started_at}|{resolved_at}".encode(), usedforsecurity=False,
        ).hexdigest()[:6]
        dt = datetime.fromisoformat(started_at.replace("Z", "+00:00")).astimezone(UTC)
        compact = dt.strftime("%Y%m%dT%H%M%SZ")
        expected_name = f"okta-{compact}-{sha}.md"
        assert result.name == expected_name

    @pytest.mark.asyncio
    async def test_write_is_idempotent(self, tmp_path):
        report = _sample_report()
        first = await write_postmortem(report, out_dir=tmp_path)
        assert first is not None
        mtime_before = first.stat().st_mtime

        second = await write_postmortem(report, out_dir=tmp_path)
        assert second is None
        assert first.stat().st_mtime == mtime_before

    @pytest.mark.asyncio
    async def test_write_creates_parent_dir(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        assert not nested.exists()
        report = _sample_report()
        result = await write_postmortem(report, out_dir=nested)
        assert result is not None
        assert nested.exists()
        assert result.exists()

    @pytest.mark.asyncio
    async def test_write_distinct_incidents_produce_distinct_files(self, tmp_path):
        report1 = _sample_report(
            started_at="2026-04-24T10:00:00Z",
            resolved_at="2026-04-24T11:00:00Z",
        )
        report2 = _sample_report(
            started_at="2026-04-24T14:00:00Z",
            resolved_at="2026-04-24T15:00:00Z",
        )
        path1 = await write_postmortem(report1, out_dir=tmp_path)
        path2 = await write_postmortem(report2, out_dir=tmp_path)
        assert path1 is not None
        assert path2 is not None
        assert path1.name != path2.name
        assert path1.exists()
        assert path2.exists()

    @pytest.mark.asyncio
    async def test_write_same_incident_across_runs_idempotent_via_sha(self, tmp_path):
        """SHA depends only on started_at + resolved_at, not event_count or other fields."""
        started_at = "2026-04-24T10:00:00Z"
        resolved_at = "2026-04-24T11:00:00Z"
        report_v1 = _sample_report(
            started_at=started_at,
            resolved_at=resolved_at,
            event_count=3,
        )
        report_v2 = _sample_report(
            started_at=started_at,
            resolved_at=resolved_at,
            event_count=99,  # Different field, same timestamps
            impact_summary="Completely different summary",
        )
        path1 = await write_postmortem(report_v1, out_dir=tmp_path)
        # v2 has same timestamps → same filename → idempotent skip
        path2 = await write_postmortem(report_v2, out_dir=tmp_path)
        assert path1 is not None
        assert path2 is None  # second write is a no-op (idempotent by filename sha)
        # File on disk still has v1 content, not v2 — first writer wins
        assert "Completely different summary" not in path1.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_write_leaves_no_tmp_on_failure(self, tmp_path, monkeypatch):
        import app.postmortems as pm_module

        def _raise(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(pm_module.os, "replace", _raise)

        report = _sample_report()
        with pytest.raises(OSError, match="disk full"):
            await write_postmortem(report, out_dir=tmp_path)

        # No .tmp files should remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Orphaned .tmp files found: {tmp_files}"


# ---------------------------------------------------------------------------
# TestAlertingEngineIntegration — async, uses in-memory db fixture
# ---------------------------------------------------------------------------


async def _seed_recovery_scenario(db, write_lock, service_id: str = "okta") -> None:
    """Seed the DB so generate_incident_report finds a complete incident window.

    Inserts a service (current_status=operational) and two status_events
    forming a >60s incident: operational→degraded then degraded→operational.
    """
    await db.execute(
        """INSERT OR REPLACE INTO services
               (id, display_name, category, poll_type, current_status)
               VALUES (?, 'Okta', 'identity', 'statuspage_json', 'operational')""",
        (service_id,),
    )
    # Event 1: started the incident (operational → degraded, >60s ago)
    await db.execute(
        """INSERT INTO status_events
               (service_id, previous_status, new_status, source, created_at)
               VALUES (?, 'operational', 'degraded', 'statuspage_json', ?)""",
        (service_id, "2026-04-24T10:00:00Z"),
    )
    # Event 2: recovery (degraded → operational)
    await db.execute(
        """INSERT INTO status_events
               (service_id, previous_status, new_status, source, created_at)
               VALUES (?, 'degraded', 'operational', 'statuspage_json', ?)""",
        (service_id, "2026-04-24T11:00:00Z"),
    )
    await db.commit()


class TestAlertingEngineIntegration:
    @pytest.mark.asyncio
    async def test_engine_calls_write_postmortem_when_enabled(
        self, db, tmp_path, monkeypatch
    ):
        from app.config import settings as real_settings
        monkeypatch.setattr(real_settings, "postmortems_enabled", True)
        monkeypatch.setattr(real_settings, "postmortems_dir", str(tmp_path))
        # Suppress slack alerting — no webhook configured
        monkeypatch.setattr(real_settings, "slack_webhook_url", None)
        # Fast alert thresholds so routing doesn't suppress
        monkeypatch.setattr(real_settings, "alert_min_state_duration_seconds", 0)
        monkeypatch.setattr(real_settings, "alert_dedup_window_seconds", 1)

        write_lock = asyncio.Lock()
        await _seed_recovery_scenario(db, write_lock, service_id="okta")

        recovery_change = StatusChange(
            service_id="okta",
            service_display_name="Okta",
            previous_status="degraded",
            new_status="operational",
            status_detail=None,
            poll_type="statuspage_json",
            status_page_url=None,
        )

        await process_changes(db, write_lock, [recovery_change])

        md_files = list(tmp_path.glob("okta-*.md"))
        assert len(md_files) == 1, f"Expected 1 postmortem file, found: {md_files}"

    @pytest.mark.asyncio
    async def test_engine_does_not_call_write_postmortem_when_disabled(
        self, db, tmp_path, monkeypatch
    ):
        from app.config import settings as real_settings
        monkeypatch.setattr(real_settings, "postmortems_enabled", False)
        monkeypatch.setattr(real_settings, "postmortems_dir", str(tmp_path))
        monkeypatch.setattr(real_settings, "slack_webhook_url", None)
        monkeypatch.setattr(real_settings, "alert_min_state_duration_seconds", 0)
        monkeypatch.setattr(real_settings, "alert_dedup_window_seconds", 1)

        write_lock = asyncio.Lock()
        await _seed_recovery_scenario(db, write_lock, service_id="okta")

        recovery_change = StatusChange(
            service_id="okta",
            service_display_name="Okta",
            previous_status="degraded",
            new_status="operational",
            status_detail=None,
            poll_type="statuspage_json",
            status_page_url=None,
        )

        await process_changes(db, write_lock, [recovery_change])

        md_files = list(tmp_path.glob("*.md"))
        assert md_files == [], f"Expected no postmortem files, found: {md_files}"

    @pytest.mark.asyncio
    async def test_engine_swallows_postmortem_write_failure(
        self, db, tmp_path, monkeypatch, caplog
    ):
        import logging

        import app.postmortems as pm_module
        from app.config import settings as real_settings

        monkeypatch.setattr(real_settings, "postmortems_enabled", True)
        monkeypatch.setattr(real_settings, "postmortems_dir", str(tmp_path))
        monkeypatch.setattr(real_settings, "slack_webhook_url", None)
        monkeypatch.setattr(real_settings, "alert_min_state_duration_seconds", 0)
        monkeypatch.setattr(real_settings, "alert_dedup_window_seconds", 1)

        # Make write_postmortem raise OSError
        async def _failing_write(report, *, out_dir):
            raise OSError("simulated disk failure")

        monkeypatch.setattr(pm_module, "write_postmortem", _failing_write)

        write_lock = asyncio.Lock()
        await _seed_recovery_scenario(db, write_lock, service_id="okta")

        recovery_change = StatusChange(
            service_id="okta",
            service_display_name="Okta",
            previous_status="degraded",
            new_status="operational",
            status_detail=None,
            poll_type="statuspage_json",
            status_page_url=None,
        )

        with caplog.at_level(logging.ERROR, logger="app.alerting.engine"):
            # Must not raise — engine swallows the error
            await process_changes(db, write_lock, [recovery_change])

        error_messages = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("postmortem" in msg.lower() for msg in error_messages), (
            f"Expected an ERROR log mentioning 'postmortem'. Got: {error_messages}"
        )
