-- 009_fix_provision_firebase_user.sql
-- Idempotent upsert of auth.users + user_profiles for Firebase users.
-- Supersedes 008: its bare ON CONFLICT (user_id) / unqualified RETURN QUERY
-- collide with the RETURNS TABLE "user_id" OUT parameter (ambiguous-column
-- error on every real call). 008 stays as the immutable historical record.

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
    ON CONFLICT ON CONSTRAINT user_profiles_user_id_key DO NOTHING;

    RETURN QUERY
    SELECT user_profiles.user_id, user_profiles.username, user_profiles.display_name,
           user_profiles.bio, user_profiles.avatar_url, user_profiles.is_public,
           user_profiles.created_at, user_profiles.updated_at
    FROM user_profiles
    WHERE user_profiles.user_id = p_uid;
END;
$$ LANGUAGE plpgsql;
