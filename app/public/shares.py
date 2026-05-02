"""Public share endpoints — delete, set-password, unlock."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.dependencies import User, get_client_ip, get_current_user
from core.rate_limit import check_password_rate_limit
from core.security import hash_password, verify_password
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SetPasswordRequest(BaseModel):
    password: str | None = Field(default=None, max_length=128)
    delete_token: str | None = None


class DeleteShareRequest(BaseModel):
    delete_token: str | None = None


class UnlockRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_share(slug: str) -> dict:
    """Fetch a share row by slug. Raises 404 if not found."""
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("shares")
        .select("*")
        .eq("slug", slug)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Share not found")
    return rows[0]


def _authorize_owner(row: dict, user: User | None, delete_token: str | None) -> None:
    """Verify the caller is the share owner or has the delete token."""
    if delete_token and row.get("delete_token") == delete_token:
        return
    if user and user.id == row.get("user_id"):
        return
    raise HTTPException(status_code=403, detail="Not authorized to modify this share")


# ---------------------------------------------------------------------------
# DELETE /shares/{slug}
# ---------------------------------------------------------------------------

@router.delete("/shares/{slug}")
async def delete_share(
    slug: str,
    body: DeleteShareRequest | None = None,
    user: User | None = Depends(get_current_user),
):
    """Delete a share. Auth: owner cookie OR delete_token in body."""
    body = body or DeleteShareRequest()
    row = await _fetch_share(slug)

    # If no JWT user, we still allow delete_token
    if user is None and not body.delete_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    _authorize_owner(row, user, body.delete_token)

    client = get_admin_client()

    # Remove from storage (best-effort)
    storage_path = row.get("storage_path")
    if storage_path:
        try:
            await asyncio.to_thread(
                lambda: client.storage.from_("shares").remove([storage_path])
            )
        except Exception:
            logger.warning("Failed to remove storage file %s", storage_path, exc_info=True)

    # Remove DB row
    await asyncio.to_thread(
        lambda: client.table("shares").delete().eq("id", row["id"]).execute()
    )

    return {"detail": "Share deleted"}


# ---------------------------------------------------------------------------
# POST /shares/{slug}/set-password
# ---------------------------------------------------------------------------

@router.post("/shares/{slug}/set-password")
async def set_password(
    slug: str,
    body: SetPasswordRequest,
    user: User | None = Depends(get_current_user),
):
    """Set or clear a share password. Auth: owner OR delete_token."""
    row = await _fetch_share(slug)

    if user is None and not body.delete_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    _authorize_owner(row, user, body.delete_token)

    # null or empty string clears the password
    if body.password:
        password_hash = hash_password(body.password)
    else:
        password_hash = None

    client = get_admin_client()
    await asyncio.to_thread(
        lambda: client.table("shares")
        .update({"password_hash": password_hash})
        .eq("id", row["id"])
        .execute()
    )

    return {"detail": "Password updated"}


# ---------------------------------------------------------------------------
# POST /shares/{slug}/unlock
# ---------------------------------------------------------------------------

@router.post("/shares/{slug}/unlock")
async def unlock_share(
    slug: str,
    request: Request,
    body: UnlockRequest,
):
    """Verify a share password. Rate-limited 5/10min per IP+slug."""
    ip = get_client_ip(request)
    rate = check_password_rate_limit(ip, slug)
    if not rate.success:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(max(rate.reset, 1))},
        )

    row = await _fetch_share(slug)

    stored_hash = row.get("password_hash")
    if not stored_hash:
        raise HTTPException(status_code=400, detail="Share is not password-protected")

    if not verify_password(body.password, stored_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")

    return {"detail": "Unlocked"}
