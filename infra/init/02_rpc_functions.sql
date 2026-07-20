-- DropItX — Additional RPC functions needed by the app
-- These were Supabase RPC functions; recreated for local PostgreSQL.

-- =========================================================================
-- search_shares — full-text search across public shares
-- =========================================================================
CREATE OR REPLACE FUNCTION search_shares(
    query_term TEXT,
    result_limit INTEGER DEFAULT 20,
    result_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
    id UUID,
    slug TEXT,
    filename TEXT,
    title TEXT,
    mime_type TEXT,
    source TEXT,
    view_count INTEGER,
    download_count INTEGER,
    created_at TIMESTAMPTZ,
    user_id UUID
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id, s.slug, s.filename, s.title, s.mime_type, s.source,
        s.view_count, s.download_count, s.created_at, s.user_id
    FROM shares s
    WHERE s.is_private = false
      AND s.burned = false
      AND (s.expires_at IS NULL OR s.expires_at > now())
      AND (
        s.content_text ILIKE '%' || query_term || '%'
        OR s.filename ILIKE '%' || query_term || '%'
        OR s.title ILIKE '%' || query_term || '%'
      )
    ORDER BY s.created_at DESC
    LIMIT result_limit OFFSET result_offset;
END;
$$ LANGUAGE plpgsql;

-- =========================================================================
-- increment_share_views — increment view count + insert share_views row
-- =========================================================================
CREATE OR REPLACE FUNCTION increment_share_views(p_share_id UUID)
RETURNS void AS $$
BEGIN
    UPDATE shares SET view_count = COALESCE(view_count, 0) + 1 WHERE id = p_share_id;
END;
$$ LANGUAGE plpgsql;

-- =========================================================================
-- Team management RPCs
-- =========================================================================

CREATE OR REPLACE FUNCTION change_team_member_role(
    p_team_id UUID,
    p_user_id UUID,
    p_new_role TEXT
) RETURNS void AS $$
BEGIN
    UPDATE team_members
    SET role = p_new_role
    WHERE team_id = p_team_id AND user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION remove_team_member(
    p_team_id UUID,
    p_user_id UUID
) RETURNS void AS $$
BEGIN
    DELETE FROM team_members WHERE team_id = p_team_id AND user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION accept_team_invite(
    p_token TEXT,
    p_user_id UUID
) RETURNS TABLE(team_id UUID, team_name TEXT) AS $$
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

CREATE OR REPLACE FUNCTION decline_team_invite(p_token TEXT)
RETURNS void AS $$
BEGIN
    UPDATE team_invitations SET status = 'declined' WHERE token = p_token;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION create_team_invite(
    p_team_id UUID,
    p_email TEXT,
    p_role TEXT,
    p_invited_by UUID,
    p_token TEXT
) RETURNS TABLE(id UUID, team_id UUID, email TEXT, role TEXT, token TEXT) AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO team_invitations (team_id, email, role, invited_by, token)
    VALUES (p_team_id, p_email, p_role, p_invited_by, p_token)
    RETURNING id INTO v_id;

    RETURN QUERY SELECT v_id, p_team_id, p_email, p_role, p_token;
END;
$$ LANGUAGE plpgsql;
