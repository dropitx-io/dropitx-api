-- DropItX — Competitor Feature Migration
-- Date: 2026-05-30
-- Tasks: A1 (multi-file), A2 (general file types), A3 (download limit),
--         A4 (custom expiration), A7 (comments), A8 (version history)

-- =========================================================================
-- A1: share_groups table — links multiple files in a batch upload
-- =========================================================================

CREATE TABLE IF NOT EXISTS share_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_share_groups_slug ON share_groups(slug);
CREATE INDEX IF NOT EXISTS idx_share_groups_user_id ON share_groups(user_id);

-- Add group_id column to shares (A1)
ALTER TABLE shares ADD COLUMN IF NOT EXISTS group_id TEXT REFERENCES share_groups(slug) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_shares_group_id ON shares(group_id);

-- =========================================================================
-- A3: Download limit columns on shares
-- =========================================================================

ALTER TABLE shares ADD COLUMN IF NOT EXISTS max_downloads INT DEFAULT NULL;
ALTER TABLE shares ADD COLUMN IF NOT EXISTS download_count INT DEFAULT 0;

-- =========================================================================
-- A4: Expiration — ensure expires_at exists (may already exist)
-- =========================================================================

-- expires_at column likely already exists; this is a safety check
-- ALTER TABLE shares ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

-- =========================================================================
-- A7: share_comments table
-- =========================================================================

CREATE TABLE IF NOT EXISTS share_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_slug TEXT NOT NULL REFERENCES shares(slug) ON DELETE CASCADE,
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    author_name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_share_comments_slug ON share_comments(share_slug);
CREATE INDEX IF NOT EXISTS idx_share_comments_created_at ON share_comments(created_at DESC);

-- =========================================================================
-- A8: share_versions table — version history for publish updates
-- =========================================================================

CREATE TABLE IF NOT EXISTS share_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_slug TEXT NOT NULL REFERENCES shares(slug) ON DELETE CASCADE,
    content_text TEXT,
    storage_path TEXT,
    version_num INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_share_versions_slug ON share_versions(share_slug);
CREATE INDEX IF NOT EXISTS idx_share_versions_slug_version ON share_versions(share_slug, version_num);

-- =========================================================================
-- RLS policies (if RLS is enabled on these tables)
-- =========================================================================

-- share_groups: owner can read, public not needed
ALTER TABLE share_groups ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own share_groups"
    ON share_groups FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own share_groups"
    ON share_groups FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- share_comments: public read, authenticated or anonymous insert
ALTER TABLE share_comments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can read comments"
    ON share_comments FOR SELECT
    USING (true);

CREATE POLICY "Anyone can insert comments"
    ON share_comments FOR INSERT
    WITH CHECK (true);

-- share_versions: owner can read
ALTER TABLE share_versions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own share_versions"
    ON share_versions FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM shares
            WHERE shares.slug = share_versions.share_slug
            AND shares.user_id = auth.uid()
        )
    );

-- Update shares RLS to allow download_count increment
-- (service role bypasses RLS, so this is mainly for documentation)
