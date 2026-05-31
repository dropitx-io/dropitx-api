-- Migration: Add one_time_download flag to shares table
-- This enables file.io-style self-destructing download links:
-- file auto-deletes after first download when flag is set.

-- Add the column
ALTER TABLE shares ADD COLUMN IF NOT EXISTS one_time_download BOOLEAN DEFAULT FALSE;

-- Add comment for documentation
COMMENT ON COLUMN shares.one_time_download
  IS 'When true, the share auto-deletes after the first download (file.io style).';

-- Create index for quick filtering of active one-time downloads
CREATE INDEX IF NOT EXISTS idx_shares_one_time_download
  ON shares (one_time_download)
  WHERE one_time_download = TRUE;
