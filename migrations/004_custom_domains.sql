-- Custom Domains table for DropItX
-- Allows teams to configure custom domains for share URLs

-- Create custom_domains table
CREATE TABLE IF NOT EXISTS custom_domains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    domain TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verifying', 'active', 'failed')),
    verification_token TEXT,
    verified_at TIMESTAMPTZ,
    ssl_status TEXT DEFAULT 'pending' CHECK (ssl_status IN ('pending', 'provisioning', 'active', 'failed')),
    ssl_issued_at TIMESTAMPTZ,
    brand_logo_url TEXT,
    brand_color TEXT CHECK (brand_color ~ '^#[0-9a-fA-F]{6}$'),
    brand_favicon_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast domain lookups (used by reverse proxy)
CREATE INDEX IF NOT EXISTS idx_custom_domains_domain ON custom_domains(domain);
CREATE INDEX IF NOT EXISTS idx_custom_domains_team_id ON custom_domains(team_id);
CREATE INDEX IF NOT EXISTS idx_custom_domains_status ON custom_domains(status);

-- RLS policies
ALTER TABLE custom_domains ENABLE ROW LEVEL SECURITY;

-- Team members can view their team's domains
CREATE POLICY "Team members can view custom domains"
    ON custom_domains FOR SELECT
    USING (
        team_id IN (
            SELECT team_id FROM team_members WHERE user_id = auth.uid()
        )
    );

-- Only owners can insert/update/delete domains
CREATE POLICY "Owners can manage custom domains"
    ON custom_domains FOR ALL
    USING (
        team_id IN (
            SELECT team_id FROM team_members
            WHERE user_id = auth.uid() AND role = 'owner'
        )
    );

-- Updated at trigger
CREATE OR REPLACE FUNCTION update_custom_domains_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_custom_domains_updated_at
    BEFORE UPDATE ON custom_domains
    FOR EACH ROW
    EXECUTE FUNCTION update_custom_domains_updated_at();

-- Function to get team config by domain (for reverse proxy)
CREATE OR REPLACE FUNCTION get_team_by_domain(p_domain TEXT)
RETURNS TABLE (
    team_id UUID,
    team_slug TEXT,
    team_name TEXT,
    brand_logo_url TEXT,
    brand_color TEXT,
    brand_favicon_url TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        cd.team_id,
        t.slug,
        t.name,
        cd.brand_logo_url,
        cd.brand_color,
        cd.brand_favicon_url
    FROM custom_domains cd
    JOIN teams t ON t.id = cd.team_id
    WHERE cd.domain = p_domain
    AND cd.status = 'active';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
