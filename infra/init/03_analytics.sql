-- DropItX — share view analytics.
-- Writes come from POST /api/analytics/track; reads from the dashboard analytics
-- endpoints. These functions take ids as arguments and do no authorization:
-- callers check ownership first.

-- =========================================================================
-- record_share_view — insert one share_views row; never touches shares.view_count
-- (GET /api/shares/{slug}/content counts views).
-- =========================================================================
CREATE OR REPLACE FUNCTION record_share_view(
    p_share_id UUID,
    p_visitor_hash TEXT,
    p_referrer TEXT DEFAULT NULL,
    p_referrer_source TEXT DEFAULT 'direct',
    p_country_code TEXT DEFAULT NULL,
    p_user_agent_class TEXT DEFAULT 'unknown'
) RETURNS void AS $$
DECLARE
    v_is_unique BOOLEAN;
BEGIN
    -- Serialize concurrent views by the same visitor so only one counts as unique.
    PERFORM pg_advisory_xact_lock(hashtext(p_share_id::TEXT || '|' || COALESCE(p_visitor_hash, '')));

    SELECT NOT EXISTS (
        SELECT 1 FROM share_views
        WHERE share_id = p_share_id
          AND visitor_hash = p_visitor_hash
          AND viewed_at > now() - INTERVAL '1 hour'
    ) INTO v_is_unique;

    INSERT INTO share_views
        (share_id, referrer, referrer_source, country_code, user_agent_class, visitor_hash, is_unique)
    VALUES
        (p_share_id, p_referrer, p_referrer_source, p_country_code, p_user_agent_class, p_visitor_hash, v_is_unique);
END;
$$ LANGUAGE plpgsql;
