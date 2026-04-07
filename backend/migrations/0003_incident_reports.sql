-- Migration 0003: Incident reports table for auto-generated post-incident reports

CREATE TABLE IF NOT EXISTS incident_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL REFERENCES services(id),
    started_at DATETIME NOT NULL,
    resolved_at DATETIME NOT NULL,
    duration_seconds INTEGER NOT NULL,
    peak_severity TEXT NOT NULL,
    affected_downstream TEXT,
    event_count INTEGER NOT NULL,
    events_json TEXT NOT NULL,
    impact_summary TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_reports_service ON incident_reports(service_id);
CREATE INDEX IF NOT EXISTS idx_reports_created ON incident_reports(created_at);
