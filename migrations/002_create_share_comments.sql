-- Migration 002: Create share_comments table for discussion/comments
-- Run this against your Supabase database (SQL Editor or migration tool)

CREATE TABLE IF NOT EXISTS share_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_id UUID NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    parent_id UUID REFERENCES share_comments(id) ON DELETE CASCADE,
    user_id UUID,                          -- NULL = anonymous
    nickname TEXT,                          -- optional display name for anon
    content TEXT NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_share_comments_share_id ON share_comments(share_id);
CREATE INDEX IF NOT EXISTS idx_share_comments_parent_id ON share_comments(parent_id);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_share_comments_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_share_comments_updated_at
    BEFORE UPDATE ON share_comments
    FOR EACH ROW
    EXECUTE FUNCTION update_share_comments_updated_at();

-- RLS: public read, service-role write
ALTER TABLE share_comments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public can read share_comments"
    ON share_comments FOR SELECT
    USING (true);

CREATE POLICY "Service role can manage share_comments"
    ON share_comments FOR ALL
    USING (auth.role() = 'service_role');
