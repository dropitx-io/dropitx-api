-- 008_provision_firebase_user.sql
-- Idempotent upsert of auth.users + user_profiles for Firebase users.
-- Called by GET /api/auth/session on every frontend load.

CREATE OR REPLACE FUNCTION provision_firebase_user(p_uid TEXT, p_email TEXT)
RETURNS TABLE (
    user_id TEXT,
    username TEXT,
    display_name TEXT,
    bio TEXT,
    avatar_url TEXT,
    is_public BOOLEAN,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
) AS $$
BEGIN
    INSERT INTO auth.users (id, email)
    VALUES (p_uid, p_email)
    ON CONFLICT (id) DO UPDATE
      SET email = COALESCE(EXCLUDED.email, auth.users.email);

    INSERT INTO user_profiles (user_id)
    VALUES (p_uid)
    ON CONFLICT (user_id) DO NOTHING;

    RETURN QUERY
    SELECT user_id, username, display_name, bio, avatar_url, is_public, created_at, updated_at
    FROM user_profiles
    WHERE user_id = p_uid;
END;
$$ LANGUAGE plpgsql;
