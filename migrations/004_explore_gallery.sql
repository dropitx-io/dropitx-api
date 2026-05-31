-- Migration: Public Gallery / Explore feature
-- Run this in Supabase SQL Editor

-- 1. Add tags column to shares (text array)
ALTER TABLE shares ADD COLUMN IF NOT EXISTS tags text[] DEFAULT '{}';

-- 2. Add username + is_public to user_profiles
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS username text UNIQUE;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS is_public boolean DEFAULT false;
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS bio text;

-- 3. Create share_stars table
CREATE TABLE IF NOT EXISTS share_stars (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    share_id uuid NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    created_at timestamptz DEFAULT now(),
    UNIQUE(share_id, user_id)
);

-- Index for fast star lookups
CREATE INDEX IF NOT EXISTS idx_share_stars_share_id ON share_stars(share_id);
CREATE INDEX IF NOT EXISTS idx_share_stars_user_id ON share_stars(user_id);

-- 4. Create trending_shares view
-- Trending score: views in last 7 days weighted by recency
CREATE OR REPLACE VIEW trending_shares AS
SELECT
    s.id,
    s.slug,
    s.filename,
    s.title,
    s.tags,
    s.view_count,
    s.download_count,
    s.created_at,
    s.user_id,
    s.mime_type,
    s.source,
    COALESCE(star_counts.star_count, 0) AS star_count,
    -- Trending score: log(views+1) * recency_boost
    (ln(GREATEST(s.view_count, 0) + 1) *
     (1.0 / (1.0 + EXTRACT(EPOCH FROM (now() - s.created_at)) / 86400.0)))
    + (ln(GREATEST(COALESCE(star_counts.star_count, 0), 0) + 1) * 2.0)
    AS trending_score
FROM shares s
LEFT JOIN (
    SELECT share_id, COUNT(*) AS star_count
    FROM share_stars
    GROUP BY share_id
) star_counts ON star_counts.share_id = s.id
WHERE s.is_private = false
  AND s.burned = false
  AND (s.expires_at IS NULL OR s.expires_at > now())
ORDER BY trending_score DESC;

-- 5. Public shares view (non-private, non-expired, non-burned)
CREATE OR REPLACE VIEW public_shares AS
SELECT
    s.id,
    s.slug,
    s.filename,
    s.title,
    s.tags,
    s.view_count,
    s.download_count,
    s.created_at,
    s.user_id,
    s.mime_type,
    s.source,
    COALESCE(star_counts.star_count, 0) AS star_count
FROM shares s
LEFT JOIN (
    SELECT share_id, COUNT(*) AS star_count
    FROM share_stars
    GROUP BY share_id
) star_counts ON star_counts.share_id = s.id
WHERE s.is_private = false
  AND s.burned = false
  AND (s.expires_at IS NULL OR s.expires_at > now());

-- 6. RPC: get_star_count
CREATE OR REPLACE FUNCTION get_star_count(p_share_id uuid)
RETURNS integer AS $$
    SELECT COUNT(*)::integer FROM share_stars WHERE share_id = p_share_id;
$$ LANGUAGE sql STABLE;

-- 7. RPC: has_user_starred
CREATE OR REPLACE FUNCTION has_user_starred(p_share_id uuid, p_user_id uuid)
RETURNS boolean AS $$
    SELECT EXISTS(SELECT 1 FROM share_stars WHERE share_id = p_share_id AND user_id = p_user_id);
$$ LANGUAGE sql STABLE;

-- 8. Enable RLS on share_stars
ALTER TABLE share_stars ENABLE ROW LEVEL SECURITY;

-- Allow public read of stars
CREATE POLICY "Stars are publicly readable" ON share_stars
    FOR SELECT USING (true);

-- Allow authenticated users to insert their own stars
CREATE POLICY "Users can star shares" ON share_stars
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Allow users to unstar (delete their own stars)
CREATE POLICY "Users can unstar shares" ON share_stars
    FOR DELETE USING (auth.uid() = user_id);

-- 9. RLS on user_profiles for public profiles
-- (Assuming user_profiles already has RLS; add public read policy)
CREATE POLICY "Public profiles are readable" ON user_profiles
    FOR SELECT USING (is_public = true);

-- 10. Index on tags for filtering
CREATE INDEX IF NOT EXISTS idx_shares_tags ON shares USING gin(tags);

-- 11. Index on user_profiles.username
CREATE INDEX IF NOT EXISTS idx_user_profiles_username ON user_profiles(username);
