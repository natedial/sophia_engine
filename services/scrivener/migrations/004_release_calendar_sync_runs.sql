-- Release calendar sync audit log
-- Run this in Supabase SQL Editor after the initial Scrivener schema.

CREATE TABLE IF NOT EXISTS release_calendar_sync_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    days_ahead INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL,
    ready BOOLEAN NOT NULL DEFAULT FALSE,
    lock_acquired BOOLEAN NOT NULL DEFAULT TRUE,
    releases_fetched INTEGER,
    releases_expected INTEGER,
    releases_inserted INTEGER,
    releases_updated INTEGER,
    dates_fetched INTEGER,
    dates_expected INTEGER,
    dates_inserted INTEGER,
    dates_skipped INTEGER,
    dates_skipped_missing_release INTEGER,
    dates_removed INTEGER,
    dates_complete BOOLEAN,
    destructive_cleanup_performed BOOLEAN,
    integrity_ok BOOLEAN,
    degraded_reason TEXT,
    missing_anchors JSONB,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_release_calendar_sync_runs_started
    ON release_calendar_sync_runs(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_release_calendar_sync_runs_status
    ON release_calendar_sync_runs(status);
