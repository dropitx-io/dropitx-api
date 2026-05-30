-- Migration 003: Create share_revisions table for version history
-- Each content update saves a revision snapshot.
-- Revisions can be listed and restored.

CREATE TABLE IF NOT EXISTS share_revisions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    share_id    UUID NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
    revision    INTEGER NOT NULL,
    content     TEXT NOT NULL,
    filename    TEXT,
    title       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for fast lookup by share_id, ordered by revision
CREATE INDEX IF NOT EXISTS idx_share_revisions_share_id
    ON share_revisions (share_id, revision DESC);

-- Index for cleanup of old revisions
CREATE INDEX IF NOT EXISTS idx_share_revisions_created_at
    ON share_revisions (created_at);

COMMENT ON TABLE share_revisions IS 'Version history snapshots for shares';
COMMENT ON COLUMN share_revisions.revision IS 'Auto-incrementing revision number per share';
COMMENT ON COLUMN share_revisions.content IS 'Content at this revision (may be encrypted)';
