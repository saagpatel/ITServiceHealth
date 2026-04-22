-- Migration 0004: Audit fields on manual status updates
--
-- Adds accountability metadata to status_events so manual overrides
-- (source='manual') record who made the change, why, and from where.
-- Fields are optional at schema level so existing rows remain valid;
-- the admin API enforces presence for new manual updates.

ALTER TABLE status_events ADD COLUMN updated_by TEXT;
ALTER TABLE status_events ADD COLUMN reason TEXT;
ALTER TABLE status_events ADD COLUMN client_ip TEXT;

CREATE INDEX IF NOT EXISTS idx_events_source_created ON status_events(source, created_at);
