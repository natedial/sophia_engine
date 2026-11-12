-- Record which sweep wrote each fetch log row, so a missed daily sweep can be
-- detected when the scheduler starts (src/scheduler/catch_up.py).
ALTER TABLE fetch_logs ADD COLUMN IF NOT EXISTS source VARCHAR(50);
ALTER TABLE fetch_logs ADD COLUMN IF NOT EXISTS job_type VARCHAR(100);
CREATE INDEX IF NOT EXISTS idx_fetch_logs_sweep
    ON fetch_logs (job_type, source, status, completed_at);
