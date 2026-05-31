"""Public share endpoints — view content, delete, set-password, unlock."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

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


class BurnShareRequest(BaseModel):
    """Optional body for burn endpoint — allows delete_token auth."""
    delete_token: str | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ShareContentResponse(BaseModel):
    """Content returned when viewing a share."""
    slug: str
    filename: str | None = None
    title: str | None = None
    content: str
    encrypted: bool = False
    encryption_iv: str | None = None
    encryption_salt: str | None = None
    burn_after_reading: bool = False
    burned: bool = False
    is_private: bool = False
    password_protected: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_share(slug: str) -> dict:
    """Fetch a share row by slug. Raises 404 if not found, 410 if expired."""
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

    row = rows[0]

    # Check if burned
    if row.get("burned"):
        raise HTTPException(status_code=410, detail="Share has been burned")

    # Check expiration
    if row.get("expires_at"):
        expires = row["expires_at"]
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires:
            # Auto-delete expired share
            await _delete_share_row(row)
            raise HTTPException(status_code=410, detail="Share has expired")

    return row


async def _delete_share_row(row: dict) -> None:
    """Delete a share and its storage (best-effort)."""
    client = get_admin_client()
    storage_path = row.get("storage_path")
    if storage_path:
        # Determine bucket from source
        source = row.get("source", "")
        bucket = "html-files" if source in ("upload", "editor") else "shares"
        try:
            await asyncio.to_thread(
                lambda: client.storage.from_(bucket).remove([storage_path])
            )
        except Exception:
            logger.warning("Failed to remove storage file %s", storage_path, exc_info=True)

    try:
        await asyncio.to_thread(
            lambda: client.table("shares").delete().eq("id", row["id"]).execute()
        )
    except Exception:
        logger.warning("Failed to delete share row %s", row["id"], exc_info=True)


def _authorize_owner(row: dict, user: User | None, delete_token: str | None) -> None:
    """Verify the caller is the share owner or has the delete token."""
    if delete_token and row.get("delete_token") == delete_token:
        return
    if user and user.id == row.get("user_id"):
        return
    raise HTTPException(status_code=403, detail="Not authorized to modify this share")


# ---------------------------------------------------------------------------
# GET /shares/{slug}/content — view share content (burn-after-reading aware)
# ---------------------------------------------------------------------------

@router.get("/shares/{slug}/content", tags=["Shares"], summary="View share content")
async def get_share_content(
    slug: str,
    request: Request,
):
    """View a share's content. Handles:
    - Expiration check (returns 410 if expired)
    - Password protection (returns 403 with password_protected=true)
    - Burn-after-reading (deletes after first view)
    - E2E encryption metadata passthrough
    """
    row = await _fetch_share(slug)

    # Check password protection
    if row.get("password_hash"):
        return ShareContentResponse(
            slug=row["slug"],
            filename=row.get("filename"),
            title=row.get("title"),
            content="",
            encrypted=row.get("encrypted", False),
            encryption_iv=row.get("encryption_iv"),
            encryption_salt=row.get("encryption_salt"),
            burn_after_reading=row.get("burn_after_reading", False),
            burned=row.get("burned", False),
            is_private=row.get("is_private", False),
            password_protected=True,
        ).model_dump()

    # Fetch content from storage
    client = get_admin_client()
    storage_path = row["storage_path"]
    source = row.get("source", "")
    bucket = "html-files" if source in ("upload", "editor") else "shares"

    try:
        resp = await asyncio.to_thread(
            lambda: client.storage.from_(bucket).download(storage_path),
        )
        content = resp.decode("utf-8") if isinstance(resp, bytes) else str(resp)
    except Exception as exc:
        logger.error("Content download failed for %s: %s", storage_path, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch content") from exc

    # Increment view count (fire-and-forget)
    asyncio.create_task(_increment_view_count(row["id"]))

    # Burn after reading: delete the share after fetching content
    if row.get("burn_after_reading"):
        asyncio.create_task(_delete_share_row(row))

    return ShareContentResponse(
        slug=row["slug"],
        filename=row.get("filename"),
        title=row.get("title"),
        content=content,
        encrypted=row.get("encrypted", False),
        encryption_iv=row.get("encryption_iv"),
        encryption_salt=row.get("encryption_salt"),
        burn_after_reading=row.get("burn_after_reading", False),
        burned=row.get("burned", False),
        is_private=row.get("is_private", False),
        password_protected=False,
    ).model_dump()


async def _increment_view_count(share_id: str) -> None:
    """Increment view count for a share (fire-and-forget)."""
    try:
        client = get_admin_client()
        # Use RPC to atomically increment
        await asyncio.to_thread(
            lambda: client.rpc("increment_view_count", {"share_id": share_id}).execute()
        )
    except Exception:
        # Fallback: direct update
        try:
            client = get_admin_client()
            resp = await asyncio.to_thread(
                lambda: client.table("shares")
                .select("view_count")
                .eq("id", share_id)
                .execute()
            )
            if resp.data:
                current = resp.data[0].get("view_count", 0)
                await asyncio.to_thread(
                    lambda: client.table("shares")
                    .update({"view_count": current + 1})
                    .eq("id", share_id)
                    .execute()
                )
        except Exception:
            logger.warning("Failed to increment view count for %s", share_id, exc_info=True)


# ---------------------------------------------------------------------------
# DELETE /shares/{slug}
# ---------------------------------------------------------------------------

@router.delete("/shares/{slug}", tags=["Shares"], summary="Delete share")
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
    await _delete_share_row(row)

    return {"detail": "Share deleted"}


# ---------------------------------------------------------------------------
# POST /shares/{slug}/set-password
# ---------------------------------------------------------------------------

@router.post("/shares/{slug}/set-password", tags=["Shares"], summary="Set share password")
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

@router.post("/shares/{slug}/unlock", tags=["Shares"], summary="Unlock share with password")
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

    # After successful unlock, return content and handle burn-after-reading
    client = get_admin_client()
    storage_path = row["storage_path"]
    source = row.get("source", "")
    bucket = "html-files" if source in ("upload", "editor") else "shares"

    try:
        resp = await asyncio.to_thread(
            lambda: client.storage.from_(bucket).download(storage_path),
        )
        content = resp.decode("utf-8") if isinstance(resp, bytes) else str(resp)
    except Exception as exc:
        logger.error("Content download failed for %s: %s", storage_path, exc)
        content = ""

    # Increment view count
    asyncio.create_task(_increment_view_count(row["id"]))

    # Burn after reading
    if row.get("burn_after_reading"):
        asyncio.create_task(_delete_share_row(row))

    return {
        "detail": "Unlocked",
        "content": content,
        "slug": row["slug"],
        "filename": row.get("filename"),
        "title": row.get("title"),
        "encrypted": row.get("encrypted", False),
        "encryption_iv": row.get("encryption_iv"),
        "encryption_salt": row.get("encryption_salt"),
        "burn_after_reading": row.get("burn_after_reading", False),
        "burned": row.get("burned", False),
    }


# ---------------------------------------------------------------------------
# POST /shares/{slug}/burn — mark share as burned (consumed)
# ---------------------------------------------------------------------------

@router.post("/shares/{slug}/burn", tags=["Shares"], summary="Burn a share (mark as consumed)")
async def burn_share(
    slug: str,
    body: BurnShareRequest | None = None,
    user: User | None = Depends(get_current_user),
):
    """Burn a share — marks it as consumed. Returns 410 Gone if already burned.

    Auth: owner cookie OR delete_token in body.
    """
    body = body or BurnShareRequest()
    row = await _fetch_share(slug)

    # Check if already burned
    if row.get("burned"):
        raise HTTPException(status_code=410, detail="Share has already been burned")

    # Authorization: require owner or delete_token
    if user is None and not body.delete_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    _authorize_owner(row, user, body.delete_token)

    # Mark as burned
    client = get_admin_client()
    await asyncio.to_thread(
        lambda: client.table("shares")
        .update({"burned": True})
        .eq("id", row["id"])
        .execute()
    )

    logger.info("Share %s burned", slug)

    return {"detail": "Share burned", "slug": slug}
