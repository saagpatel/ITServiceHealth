"""Tests for Slack alerting helpers (Phase 0: Retry-After parsing)."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from app.alerting.slack import (
    RETRY_AFTER_DEFAULT,
    RETRY_AFTER_MAX,
    _parse_retry_after,
)


class TestParseRetryAfter:
    def test_none_returns_default(self):
        assert _parse_retry_after(None) == RETRY_AFTER_DEFAULT

    def test_empty_returns_default(self):
        assert _parse_retry_after("") == RETRY_AFTER_DEFAULT

    def test_integer_seconds(self):
        assert _parse_retry_after("5") == 5

    def test_integer_with_whitespace(self):
        assert _parse_retry_after("  7  ") == 7

    def test_zero_falls_back_to_default(self):
        assert _parse_retry_after("0") == RETRY_AFTER_DEFAULT

    def test_negative_falls_back_to_default(self):
        assert _parse_retry_after("-3") == RETRY_AFTER_DEFAULT

    def test_large_value_capped(self):
        assert _parse_retry_after("99999") == RETRY_AFTER_MAX

    def test_garbage_string_returns_default(self):
        assert _parse_retry_after("two seconds") == RETRY_AFTER_DEFAULT

    def test_decimal_returns_default(self):
        # "2.5" isn't a valid int; falls through to HTTP-date parse which fails
        assert _parse_retry_after("2.5") == RETRY_AFTER_DEFAULT

    def test_http_date_future(self):
        target = datetime.now(timezone.utc) + timedelta(seconds=15)
        header = format_datetime(target, usegmt=True)
        # Allow 1-2s of slippage between header construction and parse
        result = _parse_retry_after(header)
        assert 10 <= result <= RETRY_AFTER_MAX

    def test_http_date_past_returns_default(self):
        target = datetime.now(timezone.utc) - timedelta(seconds=30)
        header = format_datetime(target, usegmt=True)
        assert _parse_retry_after(header) == RETRY_AFTER_DEFAULT
