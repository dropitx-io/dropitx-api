-- DropItX — File Requests (WeTransfer-style "Transfer to me")
-- Allows users to create request links that let others upload files to them.

-- =========================================================================
-- File requests table
-- =========================================================================

CREATE TABLE IF NOT EXISTS file_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title TEXT,
    description TEXT,
    -- Limits
    max_files INTEGER DEFAULT 10 CHECK (max_files >= 1 AND max_files <= 100),
    max_file_size_mb INTEGER DEFAULT 100 CHECK (max_file_size_mb >= 1 AND max_file_size_mb <= 2000),
    -- Expiry
    expires_at TIMESTAMPTZ NOT NULL,
    -- Uploader info requirements
    require_name BOOLEAN DEFAULT false,
    require_email BOOLEAN DEFAULT false,
    -- Status
    is_active BOOLEAN DEFAULT true,
    -- Stats
    upload_count INTEGER DEFAULT 0,
    total_size_bytes BIGINT DEFAULT 0,
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_file_requests_slug ON file_requests(slug);
CREATE INDEX IF NOT EXISTS idx_file_requests_user_id ON file_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_file_requests_expires_at ON file_requests(expires_at);

-- =========================================================================
-- File request uploads (files uploaded by anonymous users)
-- =========================================================================

CREATE TABLE IF NOT EXISTS file_request_uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_request_id UUID NOT NULL REFERENCES file_requests(id) ON DELETE CASCADE,
    -- File info
    storage_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    -- Uploader info (optional)
    uploader_name TEXT,
    uploader_email TEXT,
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_file_request_uploads_request_id ON file_request_uploads(file_request_id);

-- =========================================================================
-- RLS policies (file_requests table)
-- =========================================================================

ALTER TABLE file_requests ENABLE ROW LEVEL SECURITY;

-- Owners can do everything with their requests
CREATE POLICY "Users can manage their own file requests"
    ON file_requests FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Anyone can read active, non-expired requests (for public upload page)
CREATE POLICY "Public can view active file requests"
    ON file_requests FOR SELECT
    USING (is_active = true AND expires_at > now());

-- =========================================================================
-- RLS policies (file_request_uploads table)
-- =========================================================================

ALTER TABLE file_request_uploads ENABLE ROW LEVEL SECURITY;

-- Request owners can view uploads
CREATE POLICY "Request owners can view uploads"
    ON file_request_uploads FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM file_requests
            WHERE file_requests.id = file_request_uploads.file_request_id
            AND file_requests.user_id = auth.uid()
        )
    );

-- Anyone can insert uploads (anonymous upload to active requests)
CREATE POLICY "Anyone can upload to active requests"
    ON file_request_uploads FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM file_requests
            WHERE file_requests.id = file_request_uploads.file_request_id
            AND file_requests.is_active = true
            AND file_requests.expires_at > now()
        )
    );
