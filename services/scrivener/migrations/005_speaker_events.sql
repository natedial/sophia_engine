-- Fed speaker / Board calendar events
-- Run this in Supabase SQL Editor after prior Scrivener migrations.

-- Speakers and speeches were previously ORM-only; ensure they exist for FKs.
CREATE TABLE IF NOT EXISTS speakers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    title TEXT,
    institution TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS speeches (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    speaker_id INTEGER REFERENCES speakers(id),
    speaker_name TEXT NOT NULL,
    title TEXT,
    speech_date DATE NOT NULL,
    speech_type VARCHAR(50),
    source TEXT NOT NULL,
    content_type VARCHAR(10),
    raw_text TEXT NOT NULL,
    word_count INTEGER,
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_speeches_speaker_id ON speeches(speaker_id);
CREATE INDEX IF NOT EXISTS idx_speeches_speaker_name ON speeches(speaker_name);
CREATE INDEX IF NOT EXISTS idx_speeches_date ON speeches(speech_date);
CREATE INDEX IF NOT EXISTS idx_speeches_source ON speeches(source);
CREATE INDEX IF NOT EXISTS idx_speeches_type ON speeches(speech_type);

CREATE TABLE IF NOT EXISTS speaker_events (
    id SERIAL PRIMARY KEY,
    external_id TEXT NOT NULL UNIQUE,
    speaker_id INTEGER REFERENCES speakers(id),
    speaker_name TEXT,
    title TEXT NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    scheduled_start TIMESTAMPTZ NOT NULL,
    scheduled_end TIMESTAMPTZ,
    location TEXT,
    description TEXT,
    url TEXT,
    source TEXT NOT NULL DEFAULT 'Federal Reserve Board',
    status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
    speech_id INTEGER REFERENCES speeches(id),
    raw_payload JSONB,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_speaker_events_scheduled_start
    ON speaker_events(scheduled_start);
CREATE INDEX IF NOT EXISTS idx_speaker_events_speaker_name
    ON speaker_events(speaker_name);
CREATE INDEX IF NOT EXISTS idx_speaker_events_event_type
    ON speaker_events(event_type);
CREATE INDEX IF NOT EXISTS idx_speaker_events_status
    ON speaker_events(status);
CREATE INDEX IF NOT EXISTS idx_speaker_events_speaker_id
    ON speaker_events(speaker_id);

CREATE TABLE IF NOT EXISTS speaker_event_sync_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL,
    ready BOOLEAN NOT NULL DEFAULT FALSE,
    events_fetched INTEGER,
    events_kept INTEGER,
    events_inserted INTEGER,
    events_updated INTEGER,
    events_cancelled INTEGER,
    events_skipped INTEGER,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_speaker_event_sync_runs_started
    ON speaker_event_sync_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_speaker_event_sync_runs_status
    ON speaker_event_sync_runs(status);
