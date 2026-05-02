"""Editor publish endpoint — authenticated content sharing."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import HTTPException
from pydantic import BaseModel, Field

from app.dependencies import User, get_client_ip, get_current_user
from core.config import settings
from core.extract_text import extract_text_from_html
from core.nanoid import generate_delete_token, generate_slug
from core.rate_limit import check_upload_rate_limit
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


class PublishRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10_000_000)
    filename: str | None = None
    title: str | None = None
    is_private: bool = False
    custom_slug: str | None = Field(None, max_length=100)


class PublishResponse(BaseModel):
    slug: str
    url: str
    filename: str | None
    title: str | None
    custom_slug: str | None


@router.post("/publish", response_model=PublishResponse)
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

    # Fetch user profile for display_name
    display_name = await _fetch_display_name(user.id)

    # Upload to Supabase Storage
    client = get_admin_client()
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").upload(
                storage_path,
                body.content.encode("utf-8"),
                content_type="text/html; charset=utf-8",
                upsert=True,
            ),
        )
    except Exception as exc:
        logger.error("Storage upload failed for slug=%s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to upload content") from exc

    # Insert into shares table
    plain_text = extract_text_from_html(body.content)
    share_url = f"{settings.supabase_url}/storage/v1/object/public/html-files/{storage_path}"

    try:
        await asyncio.to_thread(
            lambda: client.table("shares").insert(
                {
                    "slug": slug,
                    "user_id": user.id,
                    "storage_path": storage_path,
                    "filename": body.filename,
                    "title": body.title,
                    "is_private": body.is_private,
                    "delete_token": delete_token,
                    "plain_text": plain_text[:5000],
                    "content_type": "html",
                    "display_name": display_name,
                }
            ).execute(),
        )
    except Exception as exc:
        logger.error("DB insert failed for slug=%s: %s", slug, exc)
        # Compensating transaction: remove uploaded file
        await _cleanup_storage(storage_path)
        raise HTTPException(status_code=500, detail="Failed to save share") from exc

    return PublishResponse(
        slug=slug,
        url=share_url,
        filename=body.filename,
        title=body.title,
        custom_slug=body.custom_slug,
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


async def _fetch_display_name(user_id: str) -> str | None:
    """Fetch display_name from user profile."""
    client = get_admin_client()
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("profiles")
            .select("display_name")
            .eq("id", user_id)
            .execute(),
        )
        rows = resp.data or []
        return rows[0].get("display_name") if rows else None
    except Exception as exc:
        logger.warning("Failed to fetch profile for user=%s: %s", user_id, exc)
        return None


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
