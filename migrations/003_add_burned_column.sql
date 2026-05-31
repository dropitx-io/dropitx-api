-- Migration 003: Add burned column to shares table
-- When burned is TRUE, the share has been consumed/burned and cannot be viewed again.

ALTER TABLE shares
    ADD COLUMN IF NOT EXISTS burned BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN shares.burned IS 'Whether the share has been burned (consumed) and cannot be viewed again';
