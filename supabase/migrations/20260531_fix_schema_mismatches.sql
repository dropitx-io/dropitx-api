-- Fix: add revoked_at column to api_keys (soft-delete support)
-- Fix: create team_invites view mapping to team_invitations table

-- 1) api_keys.revoked_at
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;

-- 2) team_invites view (code queries team_invites but actual table is team_invitations)
CREATE OR REPLACE VIEW team_invites AS
  SELECT * FROM team_invitations;

-- 3) Notify PostgREST to reload schema cache
NOTIFY pgrst, 'reload schema';
