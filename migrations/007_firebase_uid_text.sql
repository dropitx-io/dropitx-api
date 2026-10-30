-- 007_firebase_uid_text.sql
-- Switch all user-identity columns from UUID (Supabase) to TEXT (Firebase uid).
-- Non-destructive: UUID values are valid TEXT. Postgres refuses to ALTER a
-- column a view depends on, so views are dropped first and recreated after.

BEGIN;

DROP VIEW IF EXISTS public_shares;
DROP VIEW IF EXISTS trending_shares;
DROP VIEW IF EXISTS team_invites;
DROP VIEW IF EXISTS profiles;

ALTER TABLE shares           DROP CONSTRAINT IF EXISTS shares_user_id_fkey;
ALTER TABLE api_keys         DROP CONSTRAINT IF EXISTS api_keys_user_id_fkey;
ALTER TABLE teams            DROP CONSTRAINT IF EXISTS teams_owner_id_fkey;
ALTER TABLE team_members     DROP CONSTRAINT IF EXISTS team_members_user_id_fkey;
ALTER TABLE team_invitations DROP CONSTRAINT IF EXISTS team_invitations_invited_by_fkey;
ALTER TABLE team_events      DROP CONSTRAINT IF EXISTS team_events_user_id_fkey;
ALTER TABLE team_shares      DROP CONSTRAINT IF EXISTS team_shares_shared_by_fkey;
ALTER TABLE share_groups     DROP CONSTRAINT IF EXISTS share_groups_user_id_fkey;
ALTER TABLE share_revisions  DROP CONSTRAINT IF EXISTS share_revisions_user_id_fkey;
ALTER TABLE share_comments   DROP CONSTRAINT IF EXISTS share_comments_user_id_fkey;
ALTER TABLE share_stars      DROP CONSTRAINT IF EXISTS share_stars_user_id_fkey;
ALTER TABLE tags             DROP CONSTRAINT IF EXISTS tags_user_id_fkey;
ALTER TABLE folders          DROP CONSTRAINT IF EXISTS folders_user_id_fkey;
ALTER TABLE user_profiles    DROP CONSTRAINT IF EXISTS user_profiles_user_id_fkey;
ALTER TABLE file_requests    DROP CONSTRAINT IF EXISTS file_requests_user_id_fkey;

ALTER TABLE auth.users ALTER COLUMN id TYPE TEXT;
ALTER TABLE auth.users ALTER COLUMN id DROP DEFAULT;

ALTER TABLE shares           ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE api_keys         ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE teams            ALTER COLUMN owner_id  TYPE TEXT;
ALTER TABLE team_members     ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE team_invitations ALTER COLUMN invited_by TYPE TEXT;
ALTER TABLE team_events      ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE team_shares      ALTER COLUMN shared_by TYPE TEXT;
ALTER TABLE share_groups     ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE share_revisions  ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE share_comments   ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE share_stars      ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE tags             ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE folders          ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE user_profiles    ALTER COLUMN user_id   TYPE TEXT;
ALTER TABLE file_requests    ALTER COLUMN user_id   TYPE TEXT;

ALTER TABLE shares           ADD CONSTRAINT shares_user_id_fkey           FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE api_keys         ADD CONSTRAINT api_keys_user_id_fkey         FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE teams            ADD CONSTRAINT teams_owner_id_fkey           FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE team_members     ADD CONSTRAINT team_members_user_id_fkey     FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE team_invitations ADD CONSTRAINT team_invitations_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE team_events      ADD CONSTRAINT team_events_user_id_fkey      FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE team_shares      ADD CONSTRAINT team_shares_shared_by_fkey    FOREIGN KEY (shared_by) REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE share_groups     ADD CONSTRAINT share_groups_user_id_fkey     FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE share_revisions  ADD CONSTRAINT share_revisions_user_id_fkey  FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE share_comments   ADD CONSTRAINT share_comments_user_id_fkey   FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE share_stars      ADD CONSTRAINT share_stars_user_id_fkey      FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE tags             ADD CONSTRAINT tags_user_id_fkey             FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE folders          ADD CONSTRAINT folders_user_id_fkey          FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE user_profiles    ADD CONSTRAINT user_profiles_user_id_fkey    FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE file_requests    ADD CONSTRAINT file_requests_user_id_fkey    FOREIGN KEY (user_id)  REFERENCES auth.users(id) ON DELETE CASCADE;

CREATE OR REPLACE VIEW team_invites AS SELECT * FROM team_invitations;
CREATE OR REPLACE VIEW profiles AS SELECT * FROM user_profiles;

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
) star_counts ON star_counts.share_id = s.id;

CREATE OR REPLACE FUNCTION auth.uid() RETURNS TEXT
  LANGUAGE sql STABLE AS $$ SELECT NULL::TEXT; $$;

CREATE OR REPLACE FUNCTION search_shares(query_term TEXT, result_limit INTEGER DEFAULT 20, result_offset INTEGER DEFAULT 0)
RETURNS TABLE (
    id UUID, slug TEXT, filename TEXT, title TEXT, mime_type TEXT, source TEXT,
    view_count INTEGER, download_count INTEGER, created_at TIMESTAMPTZ, user_id TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT s.id, s.slug, s.filename, s.title, s.mime_type, s.source,
           s.view_count, s.download_count, s.created_at, s.user_id
    FROM shares s
    WHERE s.is_private = false AND s.burned = false
      AND (s.expires_at IS NULL OR s.expires_at > now())
      AND (s.content_text ILIKE '%' || query_term || '%'
           OR s.filename ILIKE '%' || query_term || '%'
           OR s.title ILIKE '%' || query_term || '%')
    ORDER BY s.created_at DESC
    LIMIT result_limit OFFSET result_offset;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION change_team_member_role(p_team_id UUID, p_user_id TEXT, p_new_role TEXT)
RETURNS void AS $$
BEGIN
    UPDATE team_members SET role = p_new_role WHERE team_id = p_team_id AND user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION remove_team_member(p_team_id UUID, p_user_id TEXT)
RETURNS void AS $$
BEGIN
    DELETE FROM team_members WHERE team_id = p_team_id AND user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION accept_team_invite(p_token TEXT, p_user_id TEXT)
RETURNS TABLE(team_id UUID, team_name TEXT) AS $$
DECLARE
    v_invite RECORD;
    v_team_id UUID;
    v_team_name TEXT;
BEGIN
    SELECT * INTO v_invite FROM team_invitations
    WHERE token = p_token AND status = 'pending' AND expires_at > now();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Invalid or expired invite';
    END IF;
    UPDATE team_invitations SET status = 'accepted' WHERE token = p_token;
    INSERT INTO team_members (team_id, user_id, role)
    VALUES (v_invite.team_id, p_user_id, v_invite.role)
    ON CONFLICT (team_id, user_id) DO NOTHING;
    SELECT id, name INTO v_team_id, v_team_name FROM teams WHERE id = v_invite.team_id;
    RETURN QUERY SELECT v_team_id, v_team_name;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION create_team_invite(p_team_id UUID, p_email TEXT, p_role TEXT, p_invited_by TEXT, p_token TEXT)
RETURNS TABLE(id UUID, team_id UUID, email TEXT, role TEXT, token TEXT) AS $$
DECLARE v_id UUID;
BEGIN
    INSERT INTO team_invitations (team_id, email, role, invited_by, token)
    VALUES (p_team_id, p_email, p_role, p_invited_by, p_token)
    RETURNING id INTO v_id;
    RETURN QUERY SELECT v_id, p_team_id, p_email, p_role, p_token;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION has_user_starred(p_share_id UUID, p_user_id TEXT)
RETURNS BOOLEAN AS $$
    SELECT EXISTS(SELECT 1 FROM share_stars WHERE share_id = p_share_id AND user_id = p_user_id);
$$ LANGUAGE sql;

COMMIT;
