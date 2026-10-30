-- Stubs for Supabase auth layer, so migrations referencing auth.users / auth.uid() apply on vanilla Postgres.
-- The local PostgREST shim does not enforce RLS; these exist only to satisfy CREATE POLICY and FK targets.
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (id TEXT PRIMARY KEY);

CREATE OR REPLACE FUNCTION auth.uid() RETURNS TEXT
  LANGUAGE sql STABLE AS $$
    SELECT NULL::TEXT;
  $$;

CREATE OR REPLACE FUNCTION auth.role() RETURNS TEXT
  LANGUAGE sql STABLE AS $$
    SELECT 'authenticated';
  $$;
