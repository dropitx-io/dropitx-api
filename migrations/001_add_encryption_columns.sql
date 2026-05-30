-- Migration 001: Add E2E encryption support to shares table
-- Content is stored encrypted; the server never sees plaintext.
-- encryption_iv  = base64-encoded AES-GCM initialization vector (12 bytes)
-- encryption_salt = base64-encoded PBKDF2 salt (16 bytes)
-- encrypted      = boolean flag indicating content is encrypted

ALTER TABLE shares
    ADD COLUMN IF NOT EXISTS encrypted BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS encryption_iv TEXT,
    ADD COLUMN IF NOT EXISTS encryption_salt TEXT;

COMMENT ON COLUMN shares.encrypted IS 'Whether the stored content is E2E encrypted';
COMMENT ON COLUMN shares.encryption_iv IS 'Base64-encoded AES-GCM IV (12 bytes)';
COMMENT ON COLUMN shares.encryption_salt IS 'Base64-encoded PBKDF2 salt (16 bytes)';
