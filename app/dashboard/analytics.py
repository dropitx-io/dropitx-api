"""Share view analytics for the signed-in user's own shares."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import User, get_current_user
from core.supabase import get_admin_client
from models.analytics import (
    AnalyticsShareRef,
    GeoBreakdown,
    ReferrerBreakdown,
    ShareAnalytics,
    ShareAnalyticsResponse,
    ShareTotals,
    TopShare,
    TopSharesResponse,
    ViewTimeSeriesPoint,
)

router = APIRouter()

_BREAKDOWN_LIMIT = 10


@router.get("/analytics/top-shares", response_model=TopSharesResponse, tags=["Analytics"])
async def top_shares(
    user: User = Depends(get_current_user),
    limit: int = Query(default=10, ge=1, le=50),
):
    """The caller's shares ranked by views in the last 30 days, plus totals over all their shares.

    Totals include private, expired and burned shares; the ranking skips expired ones.
    """
    client = get_admin_client()
    totals_resp, top_resp = await asyncio.gather(
        asyncio.to_thread(
            lambda: client.rpc("get_user_share_totals", {"p_user_id": user.id}).execute()
        ),
        asyncio.to_thread(
            lambda: client.rpc(
                "get_user_top_shares", {"p_user_id": user.id, "p_limit": limit}
            ).execute()
        ),
    )
    totals_row = (totals_resp.data or [{}])[0]
    return TopSharesResponse(
        totals=ShareTotals(
            share_count=totals_row.get("share_count") or 0,
            total_views=totals_row.get("total_views") or 0,
            total_size=totals_row.get("total_size") or 0,
        ),
        top=[
            TopShare(
                share_id=str(row["share_id"]),
                slug=row["slug"],
                title=row["title"],
                total_views=row["total_views"],
                unique_views=row["unique_views"],
            )
            for row in top_resp.data or []
        ],
    )


@router.get(
    "/shares/{slug}/analytics", response_model=ShareAnalyticsResponse, tags=["Analytics"]
)
async def share_analytics(
    slug: str,
    user: User = Depends(get_current_user),
    days: int = Query(default=30, ge=1, le=365),
):
    """Views summary, daily timeseries, referrer sources and countries for one of the caller's shares.

    Owner only: any other caller gets the same 404 as for a slug that does not exist.
    """
    client = get_admin_client()
    share_resp = await asyncio.to_thread(
        lambda: client.table("shares")
        .select("id, slug, title, filename")
        .eq("slug", slug)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )
    if not share_resp.data:
        raise HTTPException(status_code=404, detail="Share not found")
    share = share_resp.data[0]
    share_id = share["id"]
    summary_rows, timeseries, referrers, geo = await asyncio.gather(
        asyncio.to_thread(
            lambda: client.rpc(
                "get_share_analytics", {"p_share_id": share_id, "p_days": days}
            ).execute().data
        ),
        asyncio.to_thread(
            lambda: client.rpc(
                "get_share_view_timeseries", {"p_share_id": share_id, "p_days": days}
            ).execute().data
        ),
        asyncio.to_thread(
            lambda: client.rpc(
                "get_share_referrers",
                {"p_share_id": share_id, "p_days": days, "p_limit": _BREAKDOWN_LIMIT},
            ).execute().data
        ),
        asyncio.to_thread(
            lambda: client.rpc(
                "get_share_geo",
                {"p_share_id": share_id, "p_days": days, "p_limit": _BREAKDOWN_LIMIT},
            ).execute().data
        ),
    )
    return ShareAnalyticsResponse(
        share=AnalyticsShareRef(
            slug=share["slug"], title=share["title"], filename=share["filename"]
        ),
        days=days,
        summary=ShareAnalytics(**summary_rows[0]) if summary_rows else ShareAnalytics(),
        timeseries=[
            ViewTimeSeriesPoint(
                date=row["date"], views=row["views"], unique_views=row["unique_views"]
            )
            for row in timeseries or []
        ],
        referrers=[
            ReferrerBreakdown(referrer_source=row["referrer_source"], views=row["views"])
            for row in referrers or []
        ],
        geo=[GeoBreakdown(country_code=row["country_code"], views=row["views"]) for row in geo or []],
    )
