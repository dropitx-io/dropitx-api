"""Database client factory — local PostgreSQL + MinIO backend.

Re-exports get_admin_client/get_anon_client/get_user_client from core.db.
The original supabase-py client is replaced by our PostgREST compat shim.
Supabase Auth (JWT verification) still goes through cloud Supabase URL.
"""

from core.db import get_admin_client, get_anon_client, get_user_client

__all__ = ["get_admin_client", "get_anon_client", "get_user_client"]
