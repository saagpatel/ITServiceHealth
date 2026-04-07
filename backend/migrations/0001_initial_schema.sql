-- Migration 0001: Initial schema
-- Creates all tables for the IT Service Health Dashboard

-- Service registry: static config + current state for each monitored service
CREATE TABLE IF NOT EXISTS services (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    category TEXT NOT NULL,
    poll_type TEXT NOT NULL DEFAULT 'manual',
    poll_url TEXT,
    statuspage_component_name TEXT,
    status_page_url TEXT,
    current_status TEXT NOT NULL DEFAULT 'unknown',
    current_status_detail TEXT,
    last_polled_at DATETIME,
    last_status_change_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Status events: every status change creates a row
CREATE TABLE IF NOT EXISTS status_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL REFERENCES services(id),
    previous_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    vendor_title TEXT,
    vendor_detail TEXT,
    impact_statement TEXT,
    source TEXT NOT NULL DEFAULT 'statuspage_json',
    vendor_incident_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_service_id ON status_events(service_id);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON status_events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_service_created ON status_events(service_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_vendor_incident ON status_events(vendor_incident_id);

-- Service dependencies: directed graph (upstream breaks → downstream impacted)
CREATE TABLE IF NOT EXISTS service_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upstream_service_id TEXT NOT NULL REFERENCES services(id),
    downstream_service_id TEXT NOT NULL REFERENCES services(id),
    impact_description TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'high',
    UNIQUE(upstream_service_id, downstream_service_id)
);
CREATE INDEX IF NOT EXISTS idx_deps_upstream ON service_dependencies(upstream_service_id);
CREATE INDEX IF NOT EXISTS idx_deps_downstream ON service_dependencies(downstream_service_id);

-- Scheduled maintenance windows from vendor status pages
CREATE TABLE IF NOT EXISTS scheduled_maintenances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL REFERENCES services(id),
    vendor_maintenance_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    scheduled_for DATETIME NOT NULL,
    scheduled_until DATETIME,
    status TEXT NOT NULL DEFAULT 'scheduled',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_maint_service ON scheduled_maintenances(service_id);
CREATE INDEX IF NOT EXISTS idx_maint_scheduled ON scheduled_maintenances(scheduled_for);
