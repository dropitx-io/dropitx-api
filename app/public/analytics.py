"""Public analytics — view tracking endpoint."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.dependencies import get_client_ip
from core.rate_limit import check_analytics_rate_limit
from core.supabase import get_admin_client
from models.analytics import AnalyticsTrack

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

class TrackResponse(BaseModel):
    tracked: bool = True


# ---------------------------------------------------------------------------
# POST /analytics/track
# ---------------------------------------------------------------------------

@router.post("/analytics/track", tags=["Analytics"])
async def track_view(
    request: Request,
    body: AnalyticsTrack,
):
    """Track a share view event. Rate-limited 60/min per IP (fail-open).
    Always returns 200 to avoid exposing tracking failures to clients."""
    ip = get_client_ip(request)

    # Fail-open: if rate limit check itself fails, still allow
    if not check_analytics_rate_limit(ip):
        return TrackResponse(tracked=False)

    client = get_admin_client()

    try:
        # Verify the share exists
        share_resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("id")
            .eq("id", body.share_id)
            .execute()
        )
        if not share_resp.data:
            # Share not found — still return 200
            return TrackResponse(tracked=False)

        # Insert view record
        view_data: dict = {
            "share_id": body.share_id,
            "tracking_token": body.tracking_token,
            "ip_address": ip,
        }
        if body.referrer is not None:
            view_data["referrer"] = body.referrer
        if body.is_embed is not None:
            view_data["is_embed"] = body.is_embed

        await asyncio.to_thread(
            lambda: client.table("share_views").insert(view_data).execute()
        )

        # Increment view_count on the share row (best-effort)
        try:
            await asyncio.to_thread(
                lambda: client.rpc(
                    "increment_share_views",
                    {"p_share_id": body.share_id},
                ).execute()
            )
        except Exception:
            logger.debug(
                "increment_share_views RPC failed for %s (may not exist yet)",
                body.share_id,
            )

    except Exception:
        logger.warning("Analytics track failed for share %s", body.share_id, exc_info=True)

    # Always return 200
    return TrackResponse()
