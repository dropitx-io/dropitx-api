-- Migration 006: Add language column for syntax highlighting
-- The upload code sets this field for text/html and text/markdown files
-- but the column was never created in the database.

ALTER TABLE shares
    ADD COLUMN IF NOT EXISTS language TEXT;

COMMENT ON COLUMN shares.language IS 'Programming/markup language for syntax highlighting (Shiki language ID)';
