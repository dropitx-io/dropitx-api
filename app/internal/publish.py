"""Editor publish endpoint — authenticated content sharing."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import HTTPException
from pydantic import BaseModel, Field

from app.dependencies import User, get_client_ip, get_current_user
from core.config import settings
from core.extract_text import extract_text_from_html
from core.language_detect import detect_language
from core.nanoid import generate_delete_token, generate_slug
from core.rate_limit import check_upload_rate_limit
from core.security import hash_password
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


class PublishRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10_000_000)
    filename: str | None = None
    title: str | None = None
    is_private: bool = False
    custom_slug: str | None = Field(None, max_length=100)
    max_downloads: int | None = None
    expires_in: str | None = Field(default=None, description="Expiration: '1h','6h','24h','7d','30d' or seconds as int string")
    # E2E encryption
    encrypted: bool = False
    encryption_iv: str | None = None
    encryption_salt: str | None = None
    # Burn after reading
    burn_after_reading: bool = False
    # One-time download (file.io style)
    one_time_download: bool = False
    # Password protection
    password: str | None = Field(default=None, max_length=128)
    # Language for syntax highlighting
    language: str | None = Field(default=None, description="Programming language for syntax highlighting")


class PublishResponse(BaseModel):
    slug: str
    url: str
    filename: str | None
    title: str | None
    custom_slug: str | None
    # E2E encryption
    encrypted: bool = False
    encryption_iv: str | None = None
    encryption_salt: str | None = None
    # Burn after reading
    burn_after_reading: bool = False
    # One-time download
    one_time_download: bool = False
    # Expiration
    expires_at: str | None = None
    # Password protection
    password_protected: bool = False
    # Language for syntax highlighting
    language: str | None = None


@router.post("/publish", response_model=PublishResponse, tags=["Publish"])
async def publish(
    body: PublishRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> PublishResponse:
    """Publish HTML content from the editor. Requires authentication."""
    # Rate limit
    ip = get_client_ip(request)
    rate = await asyncio.to_thread(check_upload_rate_limit, ip)
    if not rate.success:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Resolve slug
    slug: str
    if body.custom_slug:
        slug = await _resolve_custom_slug(user.id, body.custom_slug)
    else:
        slug = generate_slug()

    storage_path = f"shares/{slug}.html"
    delete_token = generate_delete_token()

    # Upload to Supabase Storage
    client = get_admin_client()
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").upload(
                storage_path,
                body.content.encode("utf-8"),
                file_options={"content-type": "text/html; charset=utf-8", "upsert": "true"},
            ),
        )
    except Exception as exc:
        logger.error("Storage upload failed for slug=%s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to upload content") from exc

    # Insert into shares table
    plain_text = extract_text_from_html(body.content)
    share_url = f"{settings.supabase_url}/storage/v1/object/public/html-files/{storage_path}"

    # Compute expiration (A4)
    _EXPIRATION_OPTIONS = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000}
    expires_at = None
    if body.expires_in is not None:
        ei = body.expires_in.strip()
        if ei in _EXPIRATION_OPTIONS:
            secs = _EXPIRATION_OPTIONS[ei]
        else:
            try:
                secs = int(ei)
            except ValueError:
                secs = 2592000
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=secs)).isoformat()
    else:
        # Default 30 days
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=2592000)).isoformat()

    # Derive filename so it's never None (matches text/html mime_type and storage_path).
    filename = body.filename or f"{slug}.html"

    # Detect language for syntax highlighting (use derived filename so editor
    # publishes — which don't carry a filename — still get language detection)
    detected_language = detect_language(
        filename=filename,
        explicit_language=body.language,
    )

    try:
        share_data: dict = {
            "slug": slug,
            "user_id": user.id,
            "storage_path": storage_path,
            "filename": filename,
            "title": body.title,
            "is_private": body.is_private,
            "delete_token": delete_token,
            "content_text": plain_text[:5000],
            "file_size": len(body.content.encode("utf-8")),
            "mime_type": "text/html",
            "source": "editor",
            "encrypted": body.encrypted,
            "encryption_iv": body.encryption_iv,
            "encryption_salt": body.encryption_salt,
            "burn_after_reading": body.burn_after_reading,
            "one_time_download": body.one_time_download,
            "expires_at": expires_at,
        }
        if detected_language:
            share_data["language"] = detected_language
        if body.max_downloads is not None:
            share_data["max_downloads"] = body.max_downloads
        if body.password:
            share_data["password_hash"] = hash_password(body.password)

        await asyncio.to_thread(
            lambda: client.table("shares").insert(share_data).execute(),
        )
    except Exception as exc:
        logger.error("DB insert failed for slug=%s: %s", slug, exc)
        # Compensating transaction: remove uploaded file
        await _cleanup_storage(storage_path)
        raise HTTPException(status_code=500, detail="Failed to save share") from exc

    return PublishResponse(
        slug=slug,
        url=share_url,
        filename=filename,
        title=body.title,
        custom_slug=body.custom_slug,
        encrypted=body.encrypted,
        encryption_iv=body.encryption_iv,
        encryption_salt=body.encryption_salt,
        burn_after_reading=body.burn_after_reading,
        one_time_download=body.one_time_download,
        expires_at=expires_at,
        password_protected=bool(body.password),
        language=detected_language,
    )


async def _resolve_custom_slug(user_id: str, custom_slug: str) -> str:
    """Resolve custom_slug to handle/slug format and verify uniqueness."""
    client = get_admin_client()

    # Fetch user handle
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("profiles")
            .select("handle")
            .eq("id", user_id)
            .execute(),
        )
        rows = resp.data or []
        handle = rows[0]["handle"] if rows else None
    except Exception as exc:
        logger.warning("Failed to fetch handle for user=%s: %s", user_id, exc)
        handle = None

    if handle:
        full_slug = f"{handle}/{custom_slug}"
    else:
        full_slug = custom_slug

    # Check uniqueness
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("slug")
            .eq("slug", full_slug)
            .execute(),
        )
        if resp.data:
            raise HTTPException(
                status_code=409, detail="Slug already taken"
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Slug uniqueness check failed: %s", exc)
        # Proceed optimistically if check fails

    return full_slug


async def _cleanup_storage(storage_path: str) -> None:
    """Remove uploaded file from storage (compensating transaction)."""
    try:
        client = get_admin_client()
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").remove([storage_path]),
        )
    except Exception:
        logger.warning(
            "Failed to cleanup storage path=%s", storage_path, exc_info=True
        )


# ---------------------------------------------------------------------------
# PUT /publish/{slug} — update existing share with version history (A8)
# ---------------------------------------------------------------------------

class UpdatePublishRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10_000_000)
    title: str | None = None
    is_private: bool | None = None
    max_downloads: int | None = None
    expires_in: str | None = None
    encrypted: bool = False
    encryption_iv: str | None = None
    encryption_salt: str | None = None


@router.put("/publish/{slug}", response_model=PublishResponse, tags=["Publish"])
async def update_publish(
    slug: str,
    body: UpdatePublishRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> PublishResponse:
    """Update an existing share. Saves old version to history (A8)."""
    # Rate limit
    ip = get_client_ip(request)
    rate = await asyncio.to_thread(check_upload_rate_limit, ip)
    if not rate.success:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    client = get_admin_client()

    # Fetch existing share
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("*")
            .eq("slug", slug)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to fetch share for update: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch share") from exc

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Share not found")

    existing = rows[0]
    if existing.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this share")

    # Save old version (A8)
    from app.public.versions import save_version
    await save_version(
        slug=slug,
        content_text=existing.get("content_text"),
        storage_path=existing.get("storage_path"),
    )

    # Upload new content
    storage_path = f"shares/{slug}.html"
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").upload(
                storage_path,
                body.content.encode("utf-8"),
                file_options={"content-type": "text/html; charset=utf-8", "upsert": "true"},
            ),
        )
    except Exception as exc:
        logger.error("Storage upload failed for update slug=%s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to upload content") from exc

    # Build update data
    plain_text = extract_text_from_html(body.content)
    update_data: dict = {
        "content_text": plain_text[:5000],
        "file_size": len(body.content.encode("utf-8")),
        "encrypted": body.encrypted,
        "encryption_iv": body.encryption_iv,
        "encryption_salt": body.encryption_salt,
    }
    if body.title is not None:
        update_data["title"] = body.title
    if body.is_private is not None:
        update_data["is_private"] = body.is_private
    if body.max_downloads is not None:
        update_data["max_downloads"] = body.max_downloads
    if body.expires_in is not None:
        _EXPIRATION_OPTIONS = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000}
        ei = body.expires_in.strip()
        secs = _EXPIRATION_OPTIONS.get(ei, None)
        if secs is None:
            try:
                secs = int(ei)
            except ValueError:
                secs = 2592000
        update_data["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=secs)).isoformat()

    try:
        await asyncio.to_thread(
            lambda: client.table("shares")
            .update(update_data)
            .eq("slug", slug)
            .execute()
        )
    except Exception as exc:
        logger.error("DB update failed for slug=%s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to update share") from exc

    share_url = f"{settings.supabase_url}/storage/v1/object/public/html-files/{storage_path}"

    return PublishResponse(
        slug=slug,
        url=share_url,
        filename=existing.get("filename"),
        title=body.title or existing.get("title"),
        custom_slug=existing.get("custom_slug"),
        encrypted=body.encrypted,
        encryption_iv=body.encryption_iv,
        encryption_salt=body.encryption_salt,
        expires_at=update_data.get("expires_at", existing.get("expires_at")),
    )
