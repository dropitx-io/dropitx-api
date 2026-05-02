"""API key management endpoints — authenticated via cookie/JWT."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import User, get_current_user
from core.security import generate_api_key, hash_api_key
from core.supabase import get_admin_client
from models.api_key import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/keys", tags=["keys"])

# Team roles allowed to create team API keys
_EDITOR_ROLES = {"owner", "editor"}


@router.post("", response_model=ApiKeyCreateResponse, status_code=201)
async def create_key(
    body: ApiKeyCreate,
    user: User = Depends(get_current_user),
) -> ApiKeyCreateResponse:
    """Create a new API key. Returns the raw key ONCE."""
    client = get_admin_client()
    prefix = "shk_"  # personal key by default

    if body.team_id:
        # Verify team membership with editor+ role
        prefix = "sht_"
        await _verify_team_membership(client, body.team_id, user.id)

    raw_key, key_hash = generate_api_key(prefix)
    key_prefix = raw_key[:7]  # e.g. "shk_abc" or "sht_abc"

    row_data = {
        "name": body.name,
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "user_id": user.id,
        "team_id": body.team_id,
    }

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("api_keys").insert(row_data).execute(),
        )
        row = resp.data[0]
    except Exception as exc:
        logger.error("API key insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create API key") from exc

    return ApiKeyCreateResponse(
        id=row["id"],
        name=row["name"],
        key_prefix=row["key_prefix"],
        team_id=row.get("team_id"),
        last_used_at=row.get("last_used_at"),
        created_at=row["created_at"],
        key=raw_key,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_keys(
    team_id: str | None = Query(default=None),
    user: User = Depends(get_current_user),
) -> list[ApiKeyResponse]:
    """List the current user's API keys. Optionally filter by team."""
    client = get_admin_client()

    try:
        query = (
            client.table("api_keys")
            .select("id, name, key_prefix, team_id, last_used_at, created_at, revoked_at")
            .eq("user_id", user.id)
            .is_("revoked_at", "null")
        )
        if team_id:
            query = query.eq("team_id", team_id)

        resp = await asyncio.to_thread(lambda: query.order("created_at", desc=True).execute())
        rows = resp.data or []
    except Exception as exc:
        logger.error("API key list failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list API keys") from exc

    return [
        ApiKeyResponse(
            id=r["id"],
            name=r["name"],
            key_prefix=r["key_prefix"],
            team_id=r.get("team_id"),
            last_used_at=r.get("last_used_at"),
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: str,
    user: User = Depends(get_current_user),
) -> None:
    """Soft-delete (revoke) an API key."""
    client = get_admin_client()

    # Verify ownership
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("api_keys")
            .select("id, user_id, revoked_at")
            .eq("id", key_id)
            .execute(),
        )
        rows = resp.data or []
    except Exception as exc:
        logger.error("API key lookup failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to look up API key") from exc

    if not rows:
        raise HTTPException(status_code=404, detail="API key not found")

    row = rows[0]
    if row["user_id"] != user.id:
        raise HTTPException(status_code=403, detail="Not your API key")
    if row.get("revoked_at") is not None:
        raise HTTPException(status_code=410, detail="API key already revoked")

    # Soft-delete by setting revoked_at
    try:
        await asyncio.to_thread(
            lambda: client.table("api_keys")
            .update({"revoked_at": "now()"})
            .eq("id", key_id)
            .execute(),
        )
    except Exception as exc:
        logger.error("API key revoke failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to revoke API key") from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _verify_team_membership(client, team_id: str, user_id: str) -> None:
    """Ensure user is an editor+ member of the team."""
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("team_members")
            .select("role")
            .eq("team_id", team_id)
            .eq("user_id", user_id)
            .execute(),
        )
        rows = resp.data or []
    except Exception as exc:
        logger.error("Team membership check failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to verify team membership") from exc

    if not rows:
        raise HTTPException(status_code=403, detail="Not a member of this team")
    if rows[0]["role"] not in _EDITOR_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient team role (editor+ required)")
