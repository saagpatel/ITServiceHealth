-- Migration 0006: Alert quality — flap suppression, tiering, dedup log
--
-- Before this migration every vendor blip produced an alert. Three changes:
--
-- 1. Flap suppression — new `pending_status*` columns hold a tentative
--    status change for N consecutive polls before it promotes to
--    `current_status` and emits an alert. A vendor that flaps
--    operational→degraded→operational within one or two polls now
--    produces zero alerts instead of two.
--
-- 2. Tiering — `tier` + `slack_channel_override` control alert routing:
--    critical = channel with @here mention, important = channel only,
--    informational = dashboard only (no Slack at all). Sourced from
--    services.yaml via the seeder.
--
-- 3. `alert_sent_log` — durable record of every alert fired, keyed on a
--    dedup_key (vendor_incident_id when available, else
--    service_id + status + day-bucket). Enables dedup within a window
--    and gives the future ack flow something to link a Slack ts back to.

ALTER TABLE services ADD COLUMN pending_status TEXT;
ALTER TABLE services ADD COLUMN pending_status_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE services ADD COLUMN pending_status_since DATETIME;

ALTER TABLE services ADD COLUMN tier TEXT NOT NULL DEFAULT 'important';
ALTER TABLE services ADD COLUMN slack_channel_override TEXT;

CREATE INDEX IF NOT EXISTS idx_services_tier ON services(tier);

CREATE TABLE IF NOT EXISTS alert_sent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key TEXT NOT NULL,
    service_id TEXT NOT NULL REFERENCES services(id),
    status_event_id INTEGER REFERENCES status_events(id),
    severity TEXT NOT NULL,              -- 'critical' | 'important' | 'informational' | 'poller_health' | 'aggregated'
    new_status TEXT NOT NULL,
    alert_kind TEXT NOT NULL,            -- 'status_change' | 'poller_health' | 'aggregated_upstream'
    slack_channel TEXT,
    slack_ts TEXT,                       -- Slack message ts for future ack flow
    acknowledged_at DATETIME,
    acknowledged_by TEXT,
    resolved_at DATETIME,
    suppressed_by TEXT,                  -- null = fired; 'maintenance_window', 'dedup', 'tier_informational', etc.
    first_sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_alert_dedup ON alert_sent_log(dedup_key, first_sent_at);
CREATE INDEX IF NOT EXISTS idx_alert_service ON alert_sent_log(service_id, first_sent_at);
CREATE INDEX IF NOT EXISTS idx_alert_unresolved
    ON alert_sent_log(service_id, resolved_at)
    WHERE resolved_at IS NULL;
