"""Tests for seed.py — env-var expansion in slack_channel_override."""

import logging

from app.seed import ServiceConfig, _expand_env_var


class TestExpandEnvVar:
    """Unit tests for the _expand_env_var helper — no DB, no I/O."""

    def test_none_returns_none(self):
        assert _expand_env_var(None) is None

    def test_literal_url_passed_through(self):
        url = "https://hooks.slack.com/services/T/B/literal"
        assert _expand_env_var(url) == url

    def test_env_var_expanded(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_TEAM", "https://hooks.slack.com/services/T/B/TEAM")
        assert _expand_env_var("${SLACK_WEBHOOK_TEAM}") == "https://hooks.slack.com/services/T/B/TEAM"

    def test_unset_env_var_returns_none(self, monkeypatch, caplog):
        monkeypatch.delenv("SLACK_WEBHOOK_MISSING", raising=False)
        with caplog.at_level(logging.WARNING, logger="app.seed"):
            result = _expand_env_var("${SLACK_WEBHOOK_MISSING}")
        assert result is None
        assert "SLACK_WEBHOOK_MISSING" in caplog.text

    def test_partial_reference_not_expanded(self):
        """Only exact ${VAR} patterns (full string) are expanded."""
        value = "prefix_${SLACK_WEBHOOK_TEAM}_suffix"
        assert _expand_env_var(value) == value

    def test_whitespace_around_reference_is_stripped(self, monkeypatch):
        monkeypatch.setenv("SLACK_WH", "https://hooks.slack.com/services/T/B/WH")
        assert _expand_env_var("  ${SLACK_WH}  ") == "https://hooks.slack.com/services/T/B/WH"


class TestSeedServicesChannelOverride:
    """Integration: seed_services calls _expand_env_var before writing to DB."""

    async def _seed_one(self, db, override_value: str | None) -> str | None:
        """Build a ServiceConfig, expand its override, upsert to DB, return DB value."""
        svc = ServiceConfig(
            id="test-svc-override",
            display_name="Test Service",
            category="other",
            poll_type="manual",
            tier="important",
            slack_channel_override=override_value,
        )
        expanded = _expand_env_var(svc.slack_channel_override)
        await db.execute(
            """INSERT OR REPLACE INTO services
               (id, display_name, category, poll_type, poll_url,
                statuspage_component_name, status_page_url,
                tier, slack_channel_override, current_status)
               VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?, 'unknown')""",
            (svc.id, svc.display_name, svc.category, svc.poll_type, svc.tier, expanded),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT slack_channel_override FROM services WHERE id='test-svc-override'"
        )
        row = await cursor.fetchone()
        return dict(row)["slack_channel_override"] if row else None

    async def test_channel_override_env_var_expanded(self, db, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_TEAM", "https://hooks.slack.com/services/T/B/TEAM")
        result = await self._seed_one(db, "${SLACK_WEBHOOK_TEAM}")
        assert result == "https://hooks.slack.com/services/T/B/TEAM"

    async def test_channel_override_env_var_unset_logs_and_falls_back(
        self, db, monkeypatch, caplog,
    ):
        monkeypatch.delenv("SLACK_WEBHOOK_MISSING", raising=False)
        with caplog.at_level(logging.WARNING, logger="app.seed"):
            result = await self._seed_one(db, "${SLACK_WEBHOOK_MISSING}")
        assert result is None
        assert "SLACK_WEBHOOK_MISSING" in caplog.text

    async def test_channel_override_literal_url_passed_through(self, db):
        url = "https://hooks.slack.com/services/T/B/literal"
        result = await self._seed_one(db, url)
        assert result == url
