-- Phase 1: observations are insert-only, one row per vintage.
-- The local database was started fresh on 2026-11-12, so the table is
-- rebuilt rather than converted; the next sweep and the reference-series
-- backfill (scrivener backfill-vintages) refill it.

DROP TABLE IF EXISTS observations;

CREATE TABLE observations (
    id BIGSERIAL PRIMARY KEY,
    series_id INTEGER NOT NULL REFERENCES series(id),
    date DATE NOT NULL,
    value NUMERIC,
    realtime_start DATE NOT NULL,
    vintage_source VARCHAR(16) NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_observations_series_date ON observations (series_id, date);
CREATE UNIQUE INDEX idx_observations_vintage
    ON observations (series_id, date, realtime_start);
CREATE INDEX idx_observations_first_seen ON observations (first_seen_at);
