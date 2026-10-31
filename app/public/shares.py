"""Public share endpoints — view content, delete, set-password, unlock, download."""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.dependencies import User, get_client_ip, get_current_user, get_optional_user
from app.public._share_auth import authorize_owner, can_view_share, require_share_visible
from core.rate_limit import check_password_rate_limit, check_public_read_rate_limit
from core.security import hash_password, verify_password
from core.supabase import get_admin_client
from core.thumbnail import remove_thumbnail
from models.share import GroupFile, ShareMeta

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
    language: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_share(
    slug: str,
    *,
    viewer: User | None = None,
    enforce_private: bool = False,
) -> dict:
    """Fetch a share row by slug. Raises 404 if not found, 410 if expired.

    With ``enforce_private`` a private share is reported as 404 unless ``viewer``
    owns it. The check runs before the burned/expired checks so a caller who may
    not see the share cannot tell it from a missing one by status code.
    """
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

    if enforce_private:
        require_share_visible(row, viewer)

    # Check if burned
    if row.get("burned"):
        raise HTTPException(status_code=410, detail="Share has been burned")

    # Check if one-time download has been consumed
    if row.get("one_time_download") and (row.get("download_count", 0) >= 1):
        raise HTTPException(status_code=410, detail="One-time download link has been consumed")

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
        await remove_thumbnail(storage_path)
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


# ---------------------------------------------------------------------------
# GET /shares/{slug}/content — view share content (burn-after-reading aware)
# ---------------------------------------------------------------------------

@router.get("/shares/{slug}/content", tags=["Shares"], summary="View share content")
async def get_share_content(
    slug: str,
    request: Request,
    user: User | None = Depends(get_optional_user),
):
    """View a share's content. Handles:
    - Expiration check (returns 410 if expired)
    - Password protection (returns 403 with password_protected=true)
    - Burn-after-reading (deletes after first view)
    - E2E encryption metadata passthrough
    - Download limit enforcement
    """
    ip = get_client_ip(request)
    rate = check_public_read_rate_limit(ip)
    if not rate.success:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(rate.reset, 1))},
        )

    row = await _fetch_share(slug, viewer=user, enforce_private=True)

    # Check download limit
    _check_download_limit(row)

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
            language=row.get("language"),
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

    # One-time download: auto-delete after first view
    if row.get("one_time_download"):
        asyncio.create_task(_increment_download_count(row["id"]))
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
        language=row.get("language"),
    ).model_dump()


# ---------------------------------------------------------------------------
# GET /shares/{slug} — metadata and access state (no side effects)
# ---------------------------------------------------------------------------

def _is_expired(row: dict) -> bool:
    expires = row.get("expires_at")
    if not expires:
        return False
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    return datetime.now(timezone.utc) > expires


async def _visible_group_files(row: dict, viewer: User | None) -> list[GroupFile]:
    """Live siblings of a grouped share that `viewer` may see, oldest first.

    Private siblings need their owner; password-protected ones are listed for their
    owner only, as in the group download.
    """
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("shares")
        .select("slug, user_id, filename, mime_type, file_size, download_count, max_downloads, "
                "is_private, password_hash, burned, expires_at")
        .eq("group_id", row["group_id"])
        .order("created_at", desc=False)
        .execute()
    )
    files = []
    for sibling in resp.data or []:
        if sibling.get("burned") or _is_expired(sibling) or not can_view_share(sibling, viewer):
            continue
        if sibling.get("password_hash") and not _is_owner(sibling, viewer):
            continue
        files.append(GroupFile.from_row(sibling))
    return files


def _is_owner(row: dict, viewer: User | None) -> bool:
    return viewer is not None and row.get("user_id") is not None and viewer.id == row["user_id"]


@router.get(
    "/shares/{slug}",
    response_model=ShareMeta,
    tags=["Shares"],
    summary="Get share metadata",
)
async def get_share_meta(slug: str, user: User | None = Depends(get_optional_user)):
    """Metadata and access state for a share page, embed, OG image or link unfurler.

    Never returns content, the password hash or the delete token, and never counts a
    view, burns the share or deletes it: it is safe to call any number of times.
    Private shares are 404 for everyone but the owner; expired shares are 410.
    """
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("shares").select("*").eq("slug", slug).execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Share not found")
    row = rows[0]

    require_share_visible(row, user)
    if _is_expired(row):
        raise HTTPException(status_code=410, detail="Share has expired")

    group_files = await _visible_group_files(row, user) if row.get("group_id") else []
    return ShareMeta.from_row(row, is_owner=_is_owner(row, user), group_files=group_files)


async def _increment_download_count(share_id: str) -> None:
    """Increment download count for a share (fire-and-forget)."""
    try:
        client = get_admin_client()
        await asyncio.to_thread(
            lambda: client.rpc("increment_download_count", {"share_id": share_id}).execute()
        )
    except Exception:
        # Fallback: direct update
        try:
            client = get_admin_client()
            resp = await asyncio.to_thread(
                lambda: client.table("shares")
                .select("download_count")
                .eq("id", share_id)
                .execute()
            )
            if resp.data:
                current = resp.data[0].get("download_count", 0)
                await asyncio.to_thread(
                    lambda: client.table("shares")
                    .update({"download_count": current + 1})
                    .eq("id", share_id)
                    .execute()
                )
        except Exception:
            logger.warning("Failed to increment download count for %s", share_id, exc_info=True)


def _check_download_limit(row: dict) -> None:
    """Raise 429 if the share has reached its max_downloads limit."""
    max_dl = row.get("max_downloads")
    if max_dl is not None and max_dl > 0:
        current_dl = row.get("download_count", 0)
        if current_dl >= max_dl:
            raise HTTPException(
                status_code=410,
                detail=f"Download limit reached ({max_dl} downloads)",
            )


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
    user: User | None = Depends(get_optional_user),
):
    """Delete a share. Auth: owner cookie OR delete_token in body."""
    body = body or DeleteShareRequest()
    row = await _fetch_share(slug)

    # If no JWT user, we still allow delete_token
    if user is None and not body.delete_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    authorize_owner(row, user, body.delete_token)
    await _delete_share_row(row)

    return {"detail": "Share deleted"}


# ---------------------------------------------------------------------------
# POST /shares/{slug}/set-password
# ---------------------------------------------------------------------------

@router.post("/shares/{slug}/set-password", tags=["Shares"], summary="Set share password")
async def set_password(
    slug: str,
    body: SetPasswordRequest,
    user: User | None = Depends(get_optional_user),
):
    """Set or clear a share password. Auth: owner OR delete_token."""
    if user is None and not body.delete_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    row = await _fetch_share(slug)

    authorize_owner(row, user, body.delete_token)

    # null or empty string clears the password
    if body.password:
        password_hash = hash_password(body.password)
    else:
        password_hash = None

    client = get_admin_client()
    if password_hash and row.get("storage_path"):
        await remove_thumbnail(row["storage_path"])
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
    user: User | None = Depends(get_optional_user),
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

    row = await _fetch_share(slug, viewer=user, enforce_private=True)

    # Check download limit
    _check_download_limit(row)

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

    # One-time download: auto-delete after unlock
    if row.get("one_time_download"):
        asyncio.create_task(_increment_download_count(row["id"]))
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
    user: User | None = Depends(get_optional_user),
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

    authorize_owner(row, user, body.delete_token)

    # Mark as burned
    client = get_admin_client()
    if row.get("storage_path"):
        await remove_thumbnail(row["storage_path"])
    await asyncio.to_thread(
        lambda: client.table("shares")
        .update({"burned": True})
        .eq("id", row["id"])
        .execute()
    )

    logger.info("Share %s burned", slug)

    return {"detail": "Share burned", "slug": slug}


# ---------------------------------------------------------------------------
# GET /shares/{slug}/download — download share as file attachment
# ---------------------------------------------------------------------------

@router.get("/shares/{slug}/download", tags=["Shares"], summary="Download share as file")
async def download_share(
    slug: str,
    request: Request,
    password: str | None = None,
    user: User | None = Depends(get_optional_user),
):
    """Download a share's content as a file attachment.

    - Checks max_downloads limit
    - Increments download_count
    - Handles burn-after-reading (burns after download)
    - Supports ?password= query param for password-protected shares
    """
    ip = get_client_ip(request)
    rate = check_public_read_rate_limit(ip)
    if not rate.success:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(rate.reset, 1))},
        )

    row = await _fetch_share(slug, viewer=user, enforce_private=True)

    # Check download limit BEFORE serving
    _check_download_limit(row)

    # Check password protection
    if row.get("password_hash"):
        if not password:
            raise HTTPException(
                status_code=403,
                detail="Password required. Pass ?password=YOUR_PASSWORD",
            )
        if not verify_password(password, row["password_hash"]):
            # Rate limit password attempts
            ip = get_client_ip(request)
            rate = check_password_rate_limit(ip, slug)
            if not rate.success:
                raise HTTPException(
                    status_code=429,
                    detail="Too many attempts. Try again later.",
                    headers={"Retry-After": str(max(rate.reset, 1))},
                )
            raise HTTPException(status_code=401, detail="Incorrect password")

    # Fetch content from storage
    client = get_admin_client()
    storage_path = row["storage_path"]
    source = row.get("source", "")
    bucket = "html-files" if source in ("upload", "editor") else "shares"

    try:
        resp = await asyncio.to_thread(
            lambda: client.storage.from_(bucket).download(storage_path),
        )
        content_bytes = resp if isinstance(resp, bytes) else str(resp).encode("utf-8")
    except Exception as exc:
        logger.error("Download failed for %s: %s", storage_path, exc)
        raise HTTPException(status_code=500, detail="Failed to download content") from exc

    # Increment download count
    asyncio.create_task(_increment_download_count(row["id"]))

    # Increment view count
    asyncio.create_task(_increment_view_count(row["id"]))

    # Burn after reading
    if row.get("burn_after_reading"):
        asyncio.create_task(_delete_share_row(row))

    # One-time download: auto-delete after first download
    if row.get("one_time_download"):
        asyncio.create_task(_delete_share_row(row))

    # Determine filename
    filename = row.get("filename") or f"{slug}.html"
    mime_type = row.get("mime_type", "text/html; charset=utf-8")

    return StreamingResponse(
        io.BytesIO(content_bytes),
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content_bytes)),
        },
    )


# ---------------------------------------------------------------------------
# GET /shares/{slug}/download-status — check download availability
# ---------------------------------------------------------------------------

@router.get("/shares/{slug}/download-status", tags=["Shares"], summary="Check download status")
async def get_download_status(slug: str, request: Request):
    """Check if a share is available for download.

    Returns status info including:
    - available: whether the file can still be downloaded
    - one_time_download: whether this is a one-time download link
    - consumed: whether a one-time download link has been used
    - download_count: current download count
    - max_downloads: max allowed downloads (null = unlimited)
    - burn_after_reading: whether the file burns after reading
    - expired: whether the file has expired
    """
    ip = get_client_ip(request)
    rate = check_public_read_rate_limit(ip)
    if not rate.success:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(rate.reset, 1))},
        )

    client = get_admin_client()
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("slug,one_time_download,download_count,max_downloads,burn_after_reading,expires_at,burned")
            .eq("slug", slug)
            .execute()
        )
    except Exception as exc:
        logger.error("Download status query failed for %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to check download status") from exc

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Share not found")

    row = rows[0]

    # Check if burned
    if row.get("burned"):
        return {
            "slug": slug,
            "available": False,
            "status": "burned",
            "one_time_download": row.get("one_time_download", False),
            "consumed": True,
            "download_count": row.get("download_count", 0),
            "max_downloads": row.get("max_downloads"),
            "burn_after_reading": True,
            "expired": False,
        }

    # Check if one-time download consumed
    if row.get("one_time_download") and row.get("download_count", 0) >= 1:
        return {
            "slug": slug,
            "available": False,
            "status": "consumed",
            "one_time_download": True,
            "consumed": True,
            "download_count": row.get("download_count", 0),
            "max_downloads": row.get("max_downloads"),
            "burn_after_reading": row.get("burn_after_reading", False),
            "expired": False,
        }

    # Check expiration
    expired = False
    if row.get("expires_at"):
        expires_at = row["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_at:
            expired = True

    # Check max downloads
    max_dl = row.get("max_downloads")
    download_count = row.get("download_count", 0)
    limit_reached = max_dl is not None and max_dl > 0 and download_count >= max_dl

    available = not expired and not limit_reached
    status = "available" if available else ("expired" if expired else "limit_reached")

    return {
        "slug": slug,
        "available": available,
        "status": status,
        "one_time_download": row.get("one_time_download", False),
        "consumed": False,
        "download_count": download_count,
        "max_downloads": max_dl,
        "burn_after_reading": row.get("burn_after_reading", False),
        "expired": expired,
    }
