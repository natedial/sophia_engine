-- Scrivener Initial Schema
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New Query)

-- Data sources registry (FRED, BLS, Treasury, etc.)
CREATE TABLE IF NOT EXISTS sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    base_url TEXT,
    rate_limit_per_min INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Series metadata
CREATE TABLE IF NOT EXISTS series (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES sources(id),
    external_id VARCHAR(100) NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    frequency VARCHAR(20),
    units VARCHAR(100),
    seasonal_adjustment VARCHAR(20),
    last_updated TIMESTAMPTZ,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_series_source_external UNIQUE(source_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_series_source_external ON series(source_id, external_id);

-- Time series observations
CREATE TABLE IF NOT EXISTS observations (
    id BIGSERIAL PRIMARY KEY,
    series_id INTEGER REFERENCES series(id),
    date DATE NOT NULL,
    value NUMERIC,
    release_date TIMESTAMPTZ,
    revision_num INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_observations_series_date ON observations(series_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_observations_release ON observations(release_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_observations_unique ON observations(series_id, date, revision_num);

-- Scheduled data fetch jobs
CREATE TABLE IF NOT EXISTS fetch_jobs (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES sources(id),
    series_ids INTEGER[],
    schedule VARCHAR(50),
    last_run TIMESTAMPTZ,
    last_status VARCHAR(20),
    next_run TIMESTAMPTZ,
    config JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit log for fetch operations
CREATE TABLE IF NOT EXISTS fetch_logs (
    id BIGSERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES fetch_jobs(id),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    status VARCHAR(20),
    records_fetched INTEGER,
    records_inserted INTEGER,
    error_message TEXT
);

-- Economic release calendar for scheduled fetches
CREATE TABLE IF NOT EXISTS release_calendar (
    id SERIAL PRIMARY KEY,
    release_name VARCHAR(100) NOT NULL,
    source_id INTEGER REFERENCES sources(id),
    series_ids INTEGER[],
    scheduled_time TIMESTAMPTZ NOT NULL,
    actual_time TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'pending',
    fetch_triggered_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_release_calendar_scheduled ON release_calendar(scheduled_time);
CREATE INDEX IF NOT EXISTS idx_release_calendar_pending ON release_calendar(status) WHERE status = 'pending';

-- Seed the sources table with initial data
INSERT INTO sources (name, base_url, rate_limit_per_min) VALUES
    ('FRED', 'https://api.stlouisfed.org/fred', 120),
    ('BLS', 'https://api.bls.gov/publicAPI/v2', 25),
    ('TREASURY', 'https://api.fiscaldata.treasury.gov/services/api', 60)
ON CONFLICT (name) DO NOTHING;

-- Verify tables were created
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN ('sources', 'series', 'observations', 'fetch_jobs', 'fetch_logs', 'release_calendar')
ORDER BY table_name;
