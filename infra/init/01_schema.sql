-- DropItX Local PostgreSQL Schema
-- Consolidated from supabase/migrations/ + migrations/ (15 files total)
-- Adapted for vanilla PostgreSQL 16 (no Supabase auth.users, no auth.uid())

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =========================================================================
-- auth.users stub — local replacement for Supabase auth.users
-- JWT 'sub' field is a Firebase uid pointing here. We don't manage passwords
-- (Firebase Auth does), this table just satisfies FK constraints.
-- =========================================================================
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
    id TEXT PRIMARY KEY,
    email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =========================================================================
-- Core: shares
-- =========================================================================
CREATE TABLE IF NOT EXISTS shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    title TEXT,
    content TEXT,
    content_html TEXT,
    content_text TEXT,
    file_path TEXT,
    file_name TEXT,
    filename TEXT,
    storage_path TEXT,
    file_size BIGINT,
    file_type TEXT,
    mime_type TEXT,
    is_private BOOLEAN DEFAULT false,
    password_hash TEXT,
    user_id TEXT REFERENCES auth.users(id) ON DELETE SET NULL,
    view_count INTEGER DEFAULT 0,
    max_views INTEGER,
    download_count INTEGER DEFAULT 0,
    max_downloads INT DEFAULT NULL,
    delete_token TEXT,
    group_id TEXT,
    language TEXT,
    source TEXT DEFAULT 'upload',
    -- Expiration
    expires_at TIMESTAMPTZ,
    -- E2E encryption
    encrypted BOOLEAN NOT NULL DEFAULT FALSE,
    encryption_iv TEXT,
    encryption_salt TEXT,
    -- Burn after reading
    burn_after_reading BOOLEAN NOT NULL DEFAULT FALSE,
    burned BOOLEAN NOT NULL DEFAULT FALSE,
    -- One-time download
    one_time_download BOOLEAN DEFAULT FALSE,
    -- Gallery / explore
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_shares_slug ON shares(slug);
CREATE INDEX IF NOT EXISTS idx_shares_user_id ON shares(user_id);
CREATE INDEX IF NOT EXISTS idx_shares_created_at ON shares(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shares_group_id ON shares(group_id);
CREATE INDEX IF NOT EXISTS idx_shares_one_time_download
    ON shares(one_time_download) WHERE one_time_download = TRUE;

-- =========================================================================
-- API keys
-- =========================================================================
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    scopes TEXT[] DEFAULT '{}',
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);

-- =========================================================================
-- Teams + members + invitations + events
-- =========================================================================
CREATE TABLE IF NOT EXISTS teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    owner_id TEXT REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_teams_slug ON teams(slug);
CREATE INDEX IF NOT EXISTS idx_teams_owner_id ON teams(owner_id);

CREATE TABLE IF NOT EXISTS team_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID REFERENCES teams(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES auth.users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('owner', 'editor', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(team_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_team_members_team_id ON team_members(team_id);
CREATE INDEX IF NOT EXISTS idx_team_members_user_id ON team_members(user_id);

CREATE TABLE IF NOT EXISTS team_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID REFERENCES teams(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('editor', 'viewer')),
    invited_by TEXT REFERENCES auth.users(id) ON DELETE SET NULL,
    token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'declined', 'revoked')),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '7 days'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_team_invitations_team_id ON team_invitations(team_id);
CREATE INDEX IF NOT EXISTS idx_team_invitations_email ON team_invitations(email);
CREATE INDEX IF NOT EXISTS idx_team_invitations_token ON team_invitations(token);

-- View: team_invites (code queries team_invites but table is team_invitations)
CREATE OR REPLACE VIEW team_invites AS SELECT * FROM team_invitations;

CREATE TABLE IF NOT EXISTS team_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID REFERENCES teams(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES auth.users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_team_events_team_id ON team_events(team_id);

-- =========================================================================
-- Team shares (link shares to teams)
-- =========================================================================
CREATE TABLE IF NOT EXISTS team_shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID REFERENCES teams(id) ON DELETE CASCADE,
    share_id UUID REFERENCES shares(id) ON DELETE CASCADE,
    shared_by TEXT REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_team_shares_team_id ON team_shares(team_id);
CREATE INDEX IF NOT EXISTS idx_team_shares_share_id ON team_shares(share_id);

-- =========================================================================
-- Share files (multi-file), groups, revisions, versions, comments
-- =========================================================================
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

CREATE INDEX IF NOT EXISTS idx_share_files_share_id ON share_files(share_id);

CREATE TABLE IF NOT EXISTS share_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    user_id TEXT REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_share_groups_slug ON share_groups(slug);
CREATE INDEX IF NOT EXISTS idx_share_groups_user_id ON share_groups(user_id);

CREATE TABLE IF NOT EXISTS share_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_slug TEXT NOT NULL REFERENCES shares(slug) ON DELETE CASCADE,
    version_num INTEGER NOT NULL,
    title TEXT,
    content TEXT,
    content_html TEXT,
    user_id TEXT REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(share_slug, version_num)
);

CREATE INDEX IF NOT EXISTS idx_share_revisions_share_slug ON share_revisions(share_slug);

CREATE TABLE IF NOT EXISTS share_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_slug TEXT NOT NULL REFERENCES shares(slug) ON DELETE CASCADE,
    content_text TEXT,
    storage_path TEXT,
    version_num INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_share_versions_slug ON share_versions(share_slug);

CREATE TABLE IF NOT EXISTS share_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_slug TEXT NOT NULL REFERENCES shares(slug) ON DELETE CASCADE,
    user_id TEXT REFERENCES auth.users(id) ON DELETE SET NULL,
    author_name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_share_comments_slug ON share_comments(share_slug);
CREATE INDEX IF NOT EXISTS idx_share_comments_created_at ON share_comments(created_at DESC);

-- =========================================================================
-- Share views + stars + tags + folders + profiles
-- =========================================================================
CREATE TABLE IF NOT EXISTS share_views (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_slug TEXT NOT NULL REFERENCES shares(slug) ON DELETE CASCADE,
    viewer_ip TEXT,
    user_agent TEXT,
    referer TEXT,
    country TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_share_views_share_slug ON share_views(share_slug);
CREATE INDEX IF NOT EXISTS idx_share_views_created_at ON share_views(created_at DESC);

CREATE TABLE IF NOT EXISTS share_stars (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    share_id UUID NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(share_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_share_stars_share_id ON share_stars(share_id);
CREATE INDEX IF NOT EXISTS idx_share_stars_user_id ON share_stars(user_id);

CREATE TABLE IF NOT EXISTS tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tags_user_id ON tags(user_id);

CREATE TABLE IF NOT EXISTS share_tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_id UUID REFERENCES shares(id) ON DELETE CASCADE,
    tag_id UUID REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(share_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_share_tags_share_id ON share_tags(share_id);
CREATE INDEX IF NOT EXISTS idx_share_tags_tag_id ON share_tags(tag_id);

CREATE TABLE IF NOT EXISTS folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    parent_id UUID REFERENCES folders(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_folders_user_id ON folders(user_id);

-- Share-folder junction
CREATE TABLE IF NOT EXISTS share_folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_id UUID REFERENCES shares(id) ON DELETE CASCADE,
    folder_id UUID REFERENCES folders(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(share_id, folder_id)
);

CREATE INDEX IF NOT EXISTS idx_share_folders_share_id ON share_folders(share_id);

CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    username TEXT UNIQUE,
    display_name TEXT,
    bio TEXT,
    avatar_url TEXT,
    is_public BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON user_profiles(user_id);

-- profiles view alias (code uses both profiles and user_profiles)
CREATE OR REPLACE VIEW profiles AS SELECT * FROM user_profiles;

-- =========================================================================
-- Custom domains
-- =========================================================================
CREATE TABLE IF NOT EXISTS custom_domains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    domain TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verifying', 'active', 'failed')),
    verification_token TEXT,
    verified_at TIMESTAMPTZ,
    ssl_status TEXT DEFAULT 'pending' CHECK (ssl_status IN ('pending', 'provisioning', 'active', 'failed')),
    ssl_issued_at TIMESTAMPTZ,
    brand_logo_url TEXT,
    brand_color TEXT CHECK (brand_color ~ '^#[0-9a-fA-F]{6}$'),
    brand_favicon_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_custom_domains_domain ON custom_domains(domain);
CREATE INDEX IF NOT EXISTS idx_custom_domains_team_id ON custom_domains(team_id);
CREATE INDEX IF NOT EXISTS idx_custom_domains_status ON custom_domains(status);

-- =========================================================================
-- File requests + uploads
-- =========================================================================
CREATE TABLE IF NOT EXISTS file_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title TEXT,
    description TEXT,
    max_files INTEGER DEFAULT 10 CHECK (max_files >= 1 AND max_files <= 100),
    max_file_size_mb INTEGER DEFAULT 100 CHECK (max_file_size_mb >= 1 AND max_file_size_mb <= 2000),
    expires_at TIMESTAMPTZ NOT NULL,
    require_name BOOLEAN DEFAULT false,
    require_email BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    upload_count INTEGER DEFAULT 0,
    total_size_bytes BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_file_requests_slug ON file_requests(slug);
CREATE INDEX IF NOT EXISTS idx_file_requests_user_id ON file_requests(user_id);

CREATE TABLE IF NOT EXISTS file_request_uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_request_id UUID NOT NULL REFERENCES file_requests(id) ON DELETE CASCADE,
    storage_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    uploader_name TEXT,
    uploader_email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_file_request_uploads_request_id ON file_request_uploads(file_request_id);

-- =========================================================================
-- Rate limiting
-- =========================================================================
CREATE TABLE IF NOT EXISTS rate_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT NOT NULL UNIQUE,
    count INTEGER NOT NULL DEFAULT 1,
    window_start TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rate_limits_key ON rate_limits(key);

-- =========================================================================
-- Views: public_shares, trending_shares
-- =========================================================================
CREATE OR REPLACE VIEW public_shares AS
SELECT
    s.id, s.slug, s.filename, s.title, s.tags, s.view_count,
    s.download_count, s.created_at, s.user_id, s.mime_type, s.source,
    COALESCE(star_counts.star_count, 0) AS star_count
FROM shares s
LEFT JOIN (
    SELECT share_id, COUNT(*) AS star_count FROM share_stars GROUP BY share_id
) star_counts ON star_counts.share_id = s.id
WHERE s.is_private = false AND s.burned = false
  AND (s.expires_at IS NULL OR s.expires_at > now());

CREATE OR REPLACE VIEW trending_shares AS
SELECT
    s.id, s.slug, s.filename, s.title, s.tags, s.view_count,
    s.download_count, s.created_at, s.user_id, s.mime_type, s.source,
    COALESCE(star_counts.star_count, 0) AS star_count,
    (ln(GREATEST(s.view_count, 0) + 1) *
     (1.0 / (1.0 + EXTRACT(EPOCH FROM (now() - s.created_at)) / 86400.0)))
    + (ln(GREATEST(COALESCE(star_counts.star_count, 0), 0) + 1) * 2.0)
    AS trending_score
FROM shares s
LEFT JOIN (
    SELECT share_id, COUNT(*) AS star_count FROM share_stars GROUP BY share_id
) star_counts ON star_counts.share_id = s.id
WHERE s.is_private = false AND s.burned = false
  AND (s.expires_at IS NULL OR s.expires_at > now());

-- =========================================================================
-- RPC functions
-- =========================================================================
CREATE OR REPLACE FUNCTION increment_view_count(share_id UUID)
RETURNS void AS $$
BEGIN
    UPDATE shares SET view_count = COALESCE(view_count, 0) + 1 WHERE id = share_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION increment_download_count(share_id UUID)
RETURNS void AS $$
BEGIN
    UPDATE shares SET download_count = COALESCE(download_count, 0) + 1 WHERE id = share_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION check_rate_limit(
    p_key TEXT, p_max_attempts INTEGER, p_window_secs INTEGER
)
RETURNS TABLE(success BOOLEAN, remaining INTEGER, reset_at TIMESTAMPTZ) AS $$
DECLARE
    v_count INTEGER;
    v_window_start TIMESTAMPTZ;
BEGIN
    SELECT count, window_start INTO v_count, v_window_start
    FROM rate_limits WHERE key = p_key;

    IF NOT FOUND THEN
        INSERT INTO rate_limits (key, count, window_start) VALUES (p_key, 1, now());
        RETURN QUERY SELECT true, p_max_attempts - 1, now() + (p_window_secs || ' seconds')::interval;
    ELSIF now() - v_window_start > (p_window_secs || ' seconds')::interval THEN
        UPDATE rate_limits SET count = 1, window_start = now() WHERE key = p_key;
        RETURN QUERY SELECT true, p_max_attempts - 1, now() + (p_window_secs || ' seconds')::interval;
    ELSIF v_count >= p_max_attempts THEN
        RETURN QUERY SELECT false, 0, v_window_start + (p_window_secs || ' seconds')::interval;
    ELSE
        UPDATE rate_limits SET count = count + 1 WHERE key = p_key;
        RETURN QUERY SELECT true, p_max_attempts - v_count - 1, v_window_start + (p_window_secs || ' seconds')::interval;
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION get_star_count(p_share_id UUID)
RETURNS INTEGER AS $$
    SELECT COUNT(*)::INTEGER FROM share_stars WHERE share_id = p_share_id;
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION has_user_starred(p_share_id UUID, p_user_id TEXT)
RETURNS BOOLEAN AS $$
    SELECT EXISTS(SELECT 1 FROM share_stars WHERE share_id = p_share_id AND user_id = p_user_id);
$$ LANGUAGE sql;

-- =========================================================================
-- updated_at triggers
-- =========================================================================
CREATE OR REPLACE FUNCTION generic_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_shares_updated_at BEFORE UPDATE ON shares
    FOR EACH ROW EXECUTE FUNCTION generic_updated_at();
CREATE TRIGGER trigger_share_files_updated_at BEFORE UPDATE ON share_files
    FOR EACH ROW EXECUTE FUNCTION generic_updated_at();
CREATE TRIGGER trigger_custom_domains_updated_at BEFORE UPDATE ON custom_domains
    FOR EACH ROW EXECUTE FUNCTION generic_updated_at();
CREATE TRIGGER trigger_file_requests_updated_at BEFORE UPDATE ON file_requests
    FOR EACH ROW EXECUTE FUNCTION generic_updated_at();
CREATE TRIGGER trigger_user_profiles_updated_at BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION generic_updated_at();

-- Grant all to dropitx user (local dev — no RLS needed, app enforces authz)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO dropitx;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO dropitx;
GRANT ALL PRIVILEGES ON SCHEMA auth TO dropitx;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA auth TO dropitx;
