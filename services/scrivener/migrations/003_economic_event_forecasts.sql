-- Scrivener forecast storage schema
-- Run this in Supabase SQL Editor after the economic_events table exists.

CREATE TABLE IF NOT EXISTS economic_event_forecasts (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    economic_event_id UUID NULL REFERENCES economic_events(id),
    parsed_research_id BIGINT NULL,

    source TEXT NOT NULL,
    source_date DATE NULL,
    document_name TEXT NULL,
    document_link TEXT NULL,
    document_hash TEXT NULL,

    indicator_key TEXT NOT NULL,
    event_name TEXT NOT NULL,
    country TEXT NULL,
    period TEXT NULL,
    release_date DATE NULL,

    forecast_type TEXT NOT NULL,
    forecast_value_numeric NUMERIC NULL,
    forecast_value_low NUMERIC NULL,
    forecast_value_high NUMERIC NULL,
    forecast_value_text TEXT NOT NULL,
    forecast_unit TEXT NULL,

    qualifier_text TEXT NULL,
    extraction_confidence TEXT NULL,
    evidence_text TEXT NOT NULL,

    review_status TEXT NOT NULL DEFAULT 'pending',
    upload_source TEXT NOT NULL DEFAULT 'research_analysis_layer',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT economic_event_forecasts_review_status_check
        CHECK (review_status IN ('pending', 'approved', 'rejected', 'uploaded'))
);

CREATE INDEX IF NOT EXISTS idx_economic_event_forecasts_event_id
    ON economic_event_forecasts(economic_event_id);

CREATE INDEX IF NOT EXISTS idx_economic_event_forecasts_indicator_release_date
    ON economic_event_forecasts(indicator_key, release_date);

CREATE INDEX IF NOT EXISTS idx_economic_event_forecasts_source_source_date
    ON economic_event_forecasts(source, source_date);

CREATE UNIQUE INDEX IF NOT EXISTS idx_economic_event_forecasts_sem_unique
    ON economic_event_forecasts(
        parsed_research_id,
        indicator_key,
        forecast_value_text,
        release_date
    );
