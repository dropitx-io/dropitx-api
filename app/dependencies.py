"""FastAPI dependencies — auth extraction, API key validation, client IP."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from fastapi import Request
from fastapi.exceptions import HTTPException

from core.security import verify_firebase_jwt, hash_api_key
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class User:
    """Authenticated user extracted from a Firebase ID token."""
    id: str
    email: str | None = None


@dataclass(frozen=True)
class ApiKeyAuth:
    """Authenticated identity from a Bearer API key."""
    user_id: str
    key_id: str
    team_id: str | None = None


# ---------------------------------------------------------------------------
# JWT-based user extraction
# ---------------------------------------------------------------------------

async def get_firebase_claims(request: Request) -> dict:
    """Verify the Firebase Bearer token and return its claims.

    Raises HTTPException(401) on a missing or invalid token.
    """
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    try:
        return await asyncio.to_thread(verify_firebase_jwt, token)
    except (ValueError, KeyError) as exc:
        logger.debug("JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


async def get_current_user(request: Request) -> User:
    """Verify the Firebase JWT and confirm the user is provisioned locally.

    Raises HTTPException(401) on missing/invalid token or an un-provisioned user.
    Does not write — provisioning is the FE's job via /api/auth/session.
    """
    claims = await get_firebase_claims(request)
    uid = claims["sub"]

    try:
        client = get_admin_client()
        resp = await asyncio.to_thread(
            lambda: client.table("auth.users").select("id, email").eq("id", uid).execute()
        )
    except Exception as exc:
        logger.error("User lookup failed for %s: %s", uid, exc)
        raise HTTPException(status_code=500, detail="User lookup failed") from exc

    if not resp.data:
        raise HTTPException(
            status_code=401,
            detail={"code": "user_not_provisioned", "message": "User not provisioned"},
        )

    row = resp.data[0]
    return User(id=row["id"], email=row.get("email"))


async def get_optional_user(request: Request) -> User | None:
    """Optional JWT auth — returns User or None without raising."""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# API key-based auth
# ---------------------------------------------------------------------------

async def get_api_key(request: Request) -> ApiKeyAuth:
    """Validate a Bearer API key (shk_ or sht_ prefix).

    Raises HTTPException(401) on invalid/revoked key.
    """
    raw_key = _extract_bearer(request)
    if not raw_key:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not raw_key.startswith(("shk_", "sht_")):
        raise HTTPException(status_code=401, detail="Invalid API key prefix")

    key_hash = hash_api_key(raw_key)

    try:
        client = get_admin_client()
        resp = await asyncio.to_thread(
            lambda: client.table("api_keys")
            .select("id, user_id, team_id, revoked_at")
            .eq("key_hash", key_hash)
            .execute(),
        )

        rows = resp.data or []
        if not rows:
            raise HTTPException(status_code=401, detail="API key not found")

        row = rows[0]

        if row.get("revoked_at") is not None:
            raise HTTPException(status_code=401, detail="API key has been revoked")

        # If team key, verify the user is still a member
        team_id = row.get("team_id")
        if team_id:
            membership = await asyncio.to_thread(
                lambda: client.table("team_members")
                .select("id")
                .eq("team_id", team_id)
                .eq("user_id", row["user_id"])
                .execute(),
            )
            if not membership.data:
                raise HTTPException(status_code=401, detail="Team membership revoked")

        # Fire-and-forget last_used_at update
        asyncio.create_task(_update_last_used(row["id"]))

        return ApiKeyAuth(
            user_id=row["user_id"],
            key_id=row["id"],
            team_id=team_id,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("API key lookup failed: %s", exc)
        raise HTTPException(status_code=401, detail="API key validation failed") from exc


async def _update_last_used(key_id: str) -> None:
    """Fire-and-forget update of api_keys.last_used_at."""
    try:
        client = get_admin_client()
        await asyncio.to_thread(
            lambda: client.table("api_keys")
            .update({"last_used_at": "now()"})
            .eq("id", key_id)
            .execute(),
        )
    except Exception:
        logger.warning("Failed to update last_used_at for key %s", key_id, exc_info=True)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def get_client_ip(request: Request) -> str:
    """Extract client IP, trusting only CF-Connecting-IP (set by Cloudflare's edge)."""
    # X-Forwarded-For/X-Real-IP are client-controlled and unverifiable here, so a
    # spoofed value would let an attacker rotate rate-limit buckets per request.
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    if request.client:
        return request.client.host

    return "0.0.0.0"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_bearer(request: Request) -> str | None:
    """Extract Bearer token from Authorization header."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None
