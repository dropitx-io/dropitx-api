"""Public oEmbed endpoint for share embedding."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.dependencies import get_client_ip
from core.config import settings
from core.rate_limit import check_oembed_rate_limit
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_slug(url: str) -> str | None:
    """Extract share slug from a dropitx URL.

    Accepts patterns like:
      https://dropitx.com/s/abc123
      https://dropitx.com/s/abc123/
    """
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]

    # Expect /s/{slug}
    if len(path_parts) >= 2 and path_parts[0] == "s":
        return path_parts[1]

    return None


# ---------------------------------------------------------------------------
# GET /oembed
# ---------------------------------------------------------------------------

@router.get("/oembed", tags=["oEmbed"])
async def oembed(
    request: Request,
    url: str = Query(description="The share URL to embed"),
    maxwidth: int | None = Query(default=None, description="Max embed width"),
    maxheight: int | None = Query(default=None, description="Max embed height"),
):
    """oEmbed discovery endpoint. Returns JSON oEmbed response for a share URL.
    Rate-limited 60/min per IP (fail-open)."""
    ip = get_client_ip(request)
    rate = check_oembed_rate_limit(ip)
    if not rate.success:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(rate.reset, 1))},
        )

    slug = _extract_slug(url)
    if not slug:
        raise HTTPException(status_code=400, detail="Invalid or unsupported URL format")

    client = get_admin_client()

    # Fetch share row
    try:
        share_resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("id, slug, filename, title, user_id, mime_type, created_at, is_private")
            .eq("slug", slug)
            .execute()
        )
    except Exception as exc:
        logger.error("oEmbed share lookup failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error") from exc

    rows = share_resp.data or []
    # A private share is not embeddable, so it is reported like a missing one.
    if not rows or rows[0].get("is_private"):
        raise HTTPException(status_code=404, detail="Share not found")

    share = rows[0]

    # Fetch author name from user_profiles (best-effort)
    author_name = None
    if share.get("user_id"):
        try:
            profile_resp = await asyncio.to_thread(
                lambda: client.table("user_profiles")
                .select("display_name")
                .eq("user_id", share["user_id"])
                .execute()
            )
            if profile_resp.data:
                author_name = profile_resp.data[0].get("display_name")
        except Exception:
            logger.debug("Failed to fetch author profile for %s", share["user_id"])

    # Build embed dimensions
    width = min(maxwidth, 800) if maxwidth else 800
    height = min(maxheight, 600) if maxheight else 600

    # Build the iframe embed HTML
    base_url = settings.frontend_url.rstrip("/")
    embed_url = f"{base_url}/embed/{slug}"
    html = (
        f'<iframe src="{embed_url}" '
        f'width="{width}" height="{height}" '
        f'frameborder="0" allowfullscreen></iframe>'
    )

    title = share.get("title") or share.get("filename") or slug

    response = JSONResponse(content={
        "type": "rich",
        "version": "1.0",
        "title": title,
        "html": html,
        "width": width,
        "height": height,
        "provider_name": "DropItX",
        "provider_url": base_url,
        "author_name": author_name,
    })
    response.headers["cache-control"] = "public, max-age=3600"
    return response
