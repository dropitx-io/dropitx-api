"""Supabase client factory — three client types for different auth contexts."""

from supabase import create_client, Client

from core.config import settings

_client: Client | None = None


def _get_base_client() -> Client:
    """Lazy-init the base Supabase client (anon key, no user context)."""
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_anon_key)
    return _client


def get_user_client(access_token: str) -> Client:
    """Per-request client with user JWT. RLS policies apply."""
    client = _get_base_client()
    client.postgrest.auth(access_token)
    return client


def get_admin_client() -> Client:
    """Service-role client that bypasses RLS. Use ONLY for operations
    requiring RLS bypass (admin tasks, internal workers)."""
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_anon_client() -> Client:
    """Anonymous client for public endpoints (no user context)."""
    return _get_base_client()
