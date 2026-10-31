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

-- =========================================================================
-- Read functions. Every window is the last p_days calendar days (UTC), today
-- included, so a summary, a timeseries and the breakdowns of one share always add
-- up. The functions pin the session timezone to UTC so "today" does not depend on it.
-- =========================================================================

-- Summary of one share's views in the window.
CREATE OR REPLACE FUNCTION get_share_analytics(
    p_share_id UUID,
    p_days INT DEFAULT 30
) RETURNS TABLE(
    total_views BIGINT,
    unique_views BIGINT,
    views_today BIGINT,
    views_7d BIGINT,
    avg_daily_views DOUBLE PRECISION
) LANGUAGE sql STABLE SET timezone = 'UTC' AS $$
    SELECT
        COUNT(*),
        COUNT(*) FILTER (WHERE is_unique),
        COUNT(*) FILTER (WHERE viewed_at >= date_trunc('day', now())),
        -- Independent of the window: a p_days shorter than a week must not clamp it.
        (SELECT COUNT(*) FROM share_views w
          WHERE w.share_id = p_share_id
            AND w.viewed_at >= date_trunc('day', now()) - INTERVAL '6 days'),
        CASE WHEN p_days > 0 THEN round(COUNT(*)::NUMERIC / p_days, 1)::DOUBLE PRECISION ELSE 0 END
    FROM share_views
    WHERE share_id = p_share_id
      AND viewed_at >= date_trunc('day', now()) - make_interval(days => p_days - 1);
$$;

-- One row per day, oldest first, days without views included.
CREATE OR REPLACE FUNCTION get_share_view_timeseries(
    p_share_id UUID,
    p_days INT DEFAULT 30
) RETURNS TABLE(
    date DATE,
    views BIGINT,
    unique_views BIGINT
) LANGUAGE sql STABLE SET timezone = 'UTC' AS $$
    SELECT
        d::DATE,
        COUNT(v.id),
        COUNT(v.id) FILTER (WHERE v.is_unique)
    FROM generate_series(
        date_trunc('day', now()) - make_interval(days => p_days - 1),
        date_trunc('day', now()),
        INTERVAL '1 day'
    ) AS d
    LEFT JOIN share_views v
        ON v.share_id = p_share_id
       AND v.viewed_at >= d
       AND v.viewed_at < d + INTERVAL '1 day'
    GROUP BY d
    ORDER BY d;
$$;

-- Views per referrer source, most first.
CREATE OR REPLACE FUNCTION get_share_referrers(
    p_share_id UUID,
    p_days INT DEFAULT 30,
    p_limit INT DEFAULT 10
) RETURNS TABLE(
    referrer_source TEXT,
    views BIGINT
) LANGUAGE sql STABLE SET timezone = 'UTC' AS $$
    SELECT v.referrer_source, COUNT(*) AS views
    FROM share_views v
    WHERE v.share_id = p_share_id
      AND v.viewed_at >= date_trunc('day', now()) - make_interval(days => p_days - 1)
    GROUP BY v.referrer_source
    ORDER BY views DESC, v.referrer_source
    LIMIT p_limit;
$$;

-- Views per country, most first; views with no known country are left out.
CREATE OR REPLACE FUNCTION get_share_geo(
    p_share_id UUID,
    p_days INT DEFAULT 30,
    p_limit INT DEFAULT 10
) RETURNS TABLE(
    country_code TEXT,
    views BIGINT
) LANGUAGE sql STABLE SET timezone = 'UTC' AS $$
    SELECT v.country_code, COUNT(*) AS views
    FROM share_views v
    WHERE v.share_id = p_share_id
      AND v.viewed_at >= date_trunc('day', now()) - make_interval(days => p_days - 1)
      AND v.country_code IS NOT NULL
    GROUP BY v.country_code
    ORDER BY views DESC, v.country_code
    LIMIT p_limit;
$$;

-- A user's unexpired shares ranked by views in the last 30 calendar days (UTC).
CREATE OR REPLACE FUNCTION get_user_top_shares(
    p_user_id TEXT,
    p_limit INT DEFAULT 5
) RETURNS TABLE(
    share_id UUID,
    slug TEXT,
    title TEXT,
    total_views BIGINT,
    unique_views BIGINT
) LANGUAGE sql STABLE SET timezone = 'UTC' AS $$
    SELECT
        s.id,
        s.slug,
        COALESCE(s.title, s.filename),
        COALESCE(agg.total_views, 0),
        COALESCE(agg.unique_views, 0)
    FROM shares s
    LEFT JOIN (
        SELECT v.share_id,
               COUNT(*) AS total_views,
               COUNT(*) FILTER (WHERE v.is_unique) AS unique_views
        FROM share_views v
        WHERE v.viewed_at >= date_trunc('day', now()) - make_interval(days => 29)
        GROUP BY v.share_id
    ) agg ON agg.share_id = s.id
    WHERE s.user_id = p_user_id
      AND (s.expires_at IS NULL OR s.expires_at > now())
    ORDER BY COALESCE(agg.total_views, 0) DESC, s.created_at DESC
    LIMIT p_limit;
$$;

-- Counts and sizes across every share a user owns: private, expired and burned
-- included. A share with no recorded size counts as 0 bytes. unique_views and
-- shares_with_views cover the last 30 calendar days (UTC) of views on those shares.
CREATE OR REPLACE FUNCTION get_user_share_totals(
    p_user_id TEXT
) RETURNS TABLE(
    share_count BIGINT,
    total_views BIGINT,
    total_size BIGINT,
    unique_views BIGINT,
    shares_with_views BIGINT
) LANGUAGE sql STABLE SET timezone = 'UTC' AS $$
    WITH recent AS (
        SELECT v.share_id, v.is_unique
        FROM share_views v
        JOIN shares s ON s.id = v.share_id
        WHERE s.user_id = p_user_id
          AND v.viewed_at >= date_trunc('day', now()) - make_interval(days => 29)
    )
    SELECT
        COUNT(*),
        COALESCE(SUM(view_count), 0)::BIGINT,
        COALESCE(SUM(file_size), 0)::BIGINT,
        (SELECT COUNT(*) FILTER (WHERE is_unique) FROM recent),
        (SELECT COUNT(DISTINCT share_id) FROM recent)
    FROM shares
    WHERE user_id = p_user_id;
$$;
