-- Migration 004: Add increment_download_count RPC function
-- Run this against your Supabase database (SQL Editor or migration tool)

-- Atomic download count increment (avoids race conditions)
CREATE OR REPLACE FUNCTION increment_download_count(share_id UUID)
RETURNS void AS $$
BEGIN
    UPDATE shares
    SET download_count = COALESCE(download_count, 0) + 1
    WHERE id = share_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Also create increment_view_count if it doesn't exist yet
CREATE OR REPLACE FUNCTION increment_view_count(share_id UUID)
RETURNS void AS $$
BEGIN
    UPDATE shares
    SET view_count = COALESCE(view_count, 0) + 1
    WHERE id = share_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
