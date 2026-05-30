-- Migration 002: Add burn-after-reading support to shares table
-- When burn_after_reading is TRUE, the share is deleted after the first view.

ALTER TABLE shares
    ADD COLUMN IF NOT EXISTS burn_after_reading BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN shares.burn_after_reading IS 'Delete the share automatically after the first view';
