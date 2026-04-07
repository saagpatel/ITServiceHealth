-- Migration 0002: Add unique index for maintenance deduplication
-- Enables INSERT OR REPLACE upsert on (service_id, vendor_maintenance_id)
-- SQLite treats NULLs as distinct in UNIQUE constraints, so rows without
-- vendor_maintenance_id won't conflict with each other.

CREATE UNIQUE INDEX IF NOT EXISTS idx_maint_vendor_id
    ON scheduled_maintenances(service_id, vendor_maintenance_id);
