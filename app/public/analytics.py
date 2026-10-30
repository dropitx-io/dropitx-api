"""Public analytics — view tracking endpoint."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response

from app.dependencies import get_client_ip
from core.config import settings
from core.rate_limit import check_analytics_rate_limit
from core.supabase import get_admin_client
from models.analytics import AnalyticsTrack

logger = logging.getLogger(__name__)

router = APIRouter()

# Host pattern -> referrer_source, first match wins (same rules as the FE's referrer parser).
_REFERRER_SOURCES = (
    (re.compile(r"google\.|bing\.", re.I), "google"),
    (re.compile(r"(^|\.)(twitter\.com|x\.com)$", re.I), "twitter"),
    (re.compile(r"slack\.com", re.I), "slack"),
    (re.compile(r"discord\.com", re.I), "discord"),
    (re.compile(r"github\.com", re.I), "github"),
)
_BOT_UA = re.compile(r"bot|crawl|spider|slurp|preview|facebookexternalhit|headless", re.I)
_MOBILE_UA = re.compile(r"mobi|android|iphone|ipad|ipod", re.I)
_COUNTRY = re.compile(r"[A-Z]{2}")


def _referrer_source(referrer: str | None, is_embed: bool) -> str:
    if is_embed:
        return "embed"
    if not referrer:
        return "direct"
    host = urlsplit(referrer).hostname
    if not host:
        return "direct"
    if host == urlsplit(settings.frontend_url).hostname:
        return "direct"
    for pattern, source in _REFERRER_SOURCES:
        if pattern.search(host):
            return source
    return "other"


def _user_agent_class(user_agent: str) -> str:
    if not user_agent:
        return "unknown"
    if _BOT_UA.search(user_agent):
        return "bot"
    if _MOBILE_UA.search(user_agent):
        return "mobile"
    return "desktop"


def _country_code(header: str | None) -> str | None:
    """Cloudflare's cf-ipcountry; XX (unknown) and T1 (Tor) carry no country."""
    code = (header or "").strip().upper()
    return code if _COUNTRY.fullmatch(code) and code != "XX" else None


# ---------------------------------------------------------------------------
# POST /analytics/track
# ---------------------------------------------------------------------------

@router.post("/analytics/track", status_code=204, tags=["Analytics"])
async def track_view(request: Request, body: AnalyticsTrack):
    """Record one view of a share page as a share_views row.

    Does not change shares.view_count: GET /api/shares/{slug}/content counts views.
    Answers 204 whether or not a view was recorded, so the response never reveals
    whether a slug exists or is private. Rate-limited in its own per-IP bucket, so
    tracking never eats into the budget of the content reads it accompanies.
    """
    ip = get_client_ip(request)
    rate = check_analytics_rate_limit(ip)
    if not rate.success:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(rate.reset, 1))},
        )

    client = get_admin_client()
    try:
        share_resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("id, is_private")
            .eq("slug", body.slug)
            .execute()
        )
        share = share_resp.data[0] if share_resp.data else None
        if share and not share["is_private"]:
            user_agent = request.headers.get("user-agent", "")
            params = {
                "p_share_id": share["id"],
                "p_visitor_hash": hashlib.sha256(f"{ip}|{user_agent}".encode()).hexdigest(),
                "p_referrer": body.referrer,
                "p_referrer_source": _referrer_source(body.referrer, body.is_embed),
                "p_country_code": _country_code(request.headers.get("cf-ipcountry")),
                "p_user_agent_class": _user_agent_class(user_agent),
            }
            await asyncio.to_thread(lambda: client.rpc("record_share_view", params).execute())
    except Exception:
        # Analytics must never break the share page.
        logger.warning("Analytics track failed for slug %s", body.slug, exc_info=True)

    return Response(status_code=204)
