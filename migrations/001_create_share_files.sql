-- Migration 001: Create share_files table for multi-file support
-- Run this against your Supabase database (SQL Editor or migration tool)

CREATE TABLE IF NOT EXISTS share_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_id UUID NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    storage_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for fast lookup by share
CREATE INDEX IF NOT EXISTS idx_share_files_share_id ON share_files(share_id);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_share_files_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_share_files_updated_at
    BEFORE UPDATE ON share_files
    FOR EACH ROW
    EXECUTE FUNCTION update_share_files_updated_at();

-- RLS: public read, service-role write
ALTER TABLE share_files ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public can read share_files"
    ON share_files FOR SELECT
    USING (true);

CREATE POLICY "Service role can manage share_files"
    ON share_files FOR ALL
    USING (auth.role() = 'service_role');
