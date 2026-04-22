-- Migration 0005: Per-service poller health tracking
--
-- Introduces distinct "the poller is broken" vs "the service is down" signals.
-- Before this migration, a failing poller left services stuck at their
-- last-known status with no way for the UI or alerting to tell the user
-- we are flying blind. After this migration:
--
--   consecutive_failures : number of poll failures since last success
--   last_success_at      : most recent poll that parsed cleanly
--   last_failure_reason  : human summary of the most recent poller failure
--   poller_health        : healthy | degraded | broken (3 fail threshold)
--
-- The UI should render poller_health != 'healthy' as a distinct "unknown"
-- state — never "operational" — to avoid silently serving stale data.

ALTER TABLE services ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE services ADD COLUMN last_success_at DATETIME;
ALTER TABLE services ADD COLUMN last_failure_reason TEXT;
ALTER TABLE services ADD COLUMN poller_health TEXT NOT NULL DEFAULT 'healthy';

CREATE INDEX IF NOT EXISTS idx_services_poller_health ON services(poller_health);
