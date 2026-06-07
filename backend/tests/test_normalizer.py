"""Tests for status normalizer — all format mappings + edge cases."""

import pytest

from app.poller.normalizer import (
    ServiceStatus,
    normalize_current_status,
    normalize_product_feed_status,
    normalize_rss_title,
    normalize_statuspage_component,
    normalize_statuspage_indicator,
)

# ── Statuspage.io Component Status ──────────────────────────────────


class TestStatuspageComponent:
    @pytest.mark.parametrize(
        "input_status,expected",
        [
            ("operational", ServiceStatus.OPERATIONAL),
            ("degraded_performance", ServiceStatus.DEGRADED),
            ("partial_outage", ServiceStatus.PARTIAL_OUTAGE),
            ("major_outage", ServiceStatus.MAJOR_OUTAGE),
            ("under_maintenance", ServiceStatus.DEGRADED),
        ],
    )
    def test_known_statuses(self, input_status: str, expected: ServiceStatus):
        assert normalize_statuspage_component(input_status) == expected

    def test_unknown_status(self):
        assert normalize_statuspage_component("something_new") == ServiceStatus.UNKNOWN

    def test_empty_string(self):
        assert normalize_statuspage_component("") == ServiceStatus.UNKNOWN

    def test_case_insensitive(self):
        assert normalize_statuspage_component("OPERATIONAL") == ServiceStatus.OPERATIONAL
        assert normalize_statuspage_component("Major_Outage") == ServiceStatus.MAJOR_OUTAGE

    def test_whitespace_stripped(self):
        assert normalize_statuspage_component("  operational  ") == ServiceStatus.OPERATIONAL


# ── Statuspage.io Page-Level Indicator ──────────────────────────────


class TestStatuspageIndicator:
    @pytest.mark.parametrize(
        "indicator,expected",
        [
            ("none", ServiceStatus.OPERATIONAL),
            ("minor", ServiceStatus.DEGRADED),
            ("major", ServiceStatus.PARTIAL_OUTAGE),
            ("critical", ServiceStatus.MAJOR_OUTAGE),
        ],
    )
    def test_known_indicators(self, indicator: str, expected: ServiceStatus):
        assert normalize_statuspage_indicator(indicator) == expected

    def test_unknown_indicator(self):
        assert normalize_statuspage_indicator("warning") == ServiceStatus.UNKNOWN

    def test_empty_string(self):
        assert normalize_statuspage_indicator("") == ServiceStatus.UNKNOWN

    def test_case_insensitive(self):
        assert normalize_statuspage_indicator("NONE") == ServiceStatus.OPERATIONAL
        assert normalize_statuspage_indicator("Critical") == ServiceStatus.MAJOR_OUTAGE


# ── Current Status API ────────────────────────────────────────────


class TestCurrentStatus:
    def test_ok_no_incidents(self):
        response = {"status": "ok", "active_incidents": []}
        assert normalize_current_status(response) == ServiceStatus.OPERATIONAL

    def test_ok_missing_incidents_key(self):
        response = {"status": "ok"}
        assert normalize_current_status(response) == ServiceStatus.OPERATIONAL

    def test_outage_incident(self):
        response = {
            "status": "active",
            "active_incidents": [
                {"type": "outage", "title": "Major outage"},
            ],
        }
        assert normalize_current_status(response) == ServiceStatus.MAJOR_OUTAGE

    def test_incident_type(self):
        response = {
            "status": "active",
            "active_incidents": [
                {"type": "incident", "title": "Some users affected"},
            ],
        }
        assert normalize_current_status(response) == ServiceStatus.PARTIAL_OUTAGE

    def test_notice_type(self):
        response = {
            "status": "active",
            "active_incidents": [
                {"type": "notice", "title": "Planned maintenance"},
            ],
        }
        assert normalize_current_status(response) == ServiceStatus.DEGRADED

    def test_maintenance_type(self):
        response = {
            "status": "active",
            "active_incidents": [
                {"type": "maintenance", "title": "Scheduled maintenance"},
            ],
        }
        assert normalize_current_status(response) == ServiceStatus.DEGRADED

    def test_multiple_incidents_most_severe_wins(self):
        response = {
            "status": "active",
            "active_incidents": [
                {"type": "notice", "title": "Maintenance"},
                {"type": "outage", "title": "Full outage"},
                {"type": "incident", "title": "Some issue"},
            ],
        }
        assert normalize_current_status(response) == ServiceStatus.MAJOR_OUTAGE

    def test_unknown_incident_type(self):
        response = {
            "status": "active",
            "active_incidents": [
                {"type": "something_new", "title": "Unknown type"},
            ],
        }
        assert normalize_current_status(response) == ServiceStatus.DEGRADED

    def test_non_ok_no_incidents(self):
        response = {"status": "active", "active_incidents": []}
        assert normalize_current_status(response) == ServiceStatus.DEGRADED


# ── Product Feed ──────────────────────────────────────────────────


class TestProductFeedStatus:
    def test_no_incidents_operational(self):
        assert normalize_product_feed_status([], "google-mail") == ServiceStatus.OPERATIONAL

    def test_active_incident_for_product(self):
        incidents = [
            {
                "affected_products": [{"title": "Gmail"}],
                "most_recent_update": {"status": "SERVICE_DISRUPTION"},
            },
        ]
        assert (
            normalize_product_feed_status(incidents, "google-mail") == ServiceStatus.PARTIAL_OUTAGE
        )

    def test_active_outage_for_product(self):
        incidents = [
            {
                "affected_products": [{"title": "Gmail"}],
                "most_recent_update": {"status": "SERVICE_OUTAGE"},
            },
        ]
        assert normalize_product_feed_status(incidents, "google-mail") == ServiceStatus.MAJOR_OUTAGE

    def test_resolved_incident_is_operational(self):
        incidents = [
            {
                "affected_products": [{"title": "Gmail"}],
                "end": "2026-04-01T00:00:00Z",
                "most_recent_update": {"status": "SERVICE_DISRUPTION"},
            },
        ]
        assert normalize_product_feed_status(incidents, "google-mail") == ServiceStatus.OPERATIONAL

    def test_incident_for_different_product(self):
        incidents = [
            {
                "affected_products": [{"title": "Google Drive"}],
                "most_recent_update": {"status": "SERVICE_OUTAGE"},
            },
        ]
        assert normalize_product_feed_status(incidents, "google-mail") == ServiceStatus.OPERATIONAL

    def test_calendar_product(self):
        incidents = [
            {
                "affected_products": [{"title": "Google Calendar"}],
                "most_recent_update": {"status": "degraded"},
            },
        ]
        assert normalize_product_feed_status(incidents, "google-calendar") == ServiceStatus.DEGRADED

    def test_unknown_service_id(self):
        assert normalize_product_feed_status([], "google-drive") == ServiceStatus.UNKNOWN


# ── RSS Feed ──────────────────────────────────────────────────────


class TestRSSTitle:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Major outage affecting all users", ServiceStatus.MAJOR_OUTAGE),
            ("Service outage in progress", ServiceStatus.MAJOR_OUTAGE),
            ("System completely unavailable", ServiceStatus.MAJOR_OUTAGE),
            ("Partial outage for some regions", ServiceStatus.PARTIAL_OUTAGE),
            ("Partial disruption to service", ServiceStatus.PARTIAL_OUTAGE),
            ("Some users experiencing errors", ServiceStatus.PARTIAL_OUTAGE),
            ("Degraded performance detected", ServiceStatus.DEGRADED),
            ("Performance issue with API", ServiceStatus.DEGRADED),
            ("Intermittent connectivity issues", ServiceStatus.DEGRADED),
            ("Delays in message delivery", ServiceStatus.DEGRADED),
            ("Investigating reports of issues", ServiceStatus.DEGRADED),
            ("Issue resolved - service recovered", ServiceStatus.OPERATIONAL),
            ("All systems operational", ServiceStatus.OPERATIONAL),
            ("Service has recovered", ServiceStatus.OPERATIONAL),
            ("Fix implemented and verified", ServiceStatus.OPERATIONAL),
        ],
    )
    def test_keyword_matching(self, title: str, expected: ServiceStatus):
        assert normalize_rss_title(title) == expected

    def test_no_matching_keywords(self):
        assert normalize_rss_title("New feature announcement") == ServiceStatus.UNKNOWN

    def test_empty_string(self):
        assert normalize_rss_title("") == ServiceStatus.UNKNOWN

    def test_case_insensitive(self):
        assert normalize_rss_title("MAJOR OUTAGE") == ServiceStatus.MAJOR_OUTAGE

    def test_most_severe_wins(self):
        # "major outage" matches MAJOR_OUTAGE before "investigating" matches DEGRADED
        assert normalize_rss_title("Major outage - investigating") == ServiceStatus.MAJOR_OUTAGE
