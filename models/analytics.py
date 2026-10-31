"""Pydantic models for analytics tracking and share stats."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class AnalyticsTrack(BaseModel):
    """Payload for recording one view of a share page."""
    slug: str = Field(min_length=1, max_length=200)
    referrer: str | None = Field(default=None, max_length=2048)
    is_embed: bool = False


class ShareAnalytics(BaseModel):
    """Aggregate analytics for a share."""
    total_views: int = 0
    unique_views: int = 0
    views_today: int = 0
    views_7d: int = 0
    avg_daily_views: float = 0.0


class ShareTotals(BaseModel):
    """Counts across every share the caller owns, however old or hidden."""
    share_count: int = 0
    total_views: int = 0
    total_size: int = 0


class TopShare(BaseModel):
    """One of the caller's shares ranked by views in the last 30 days."""
    share_id: str
    slug: str
    title: str | None = None
    total_views: int = 0
    unique_views: int = 0


class TopSharesResponse(BaseModel):
    totals: ShareTotals
    top: list[TopShare]


class AnalyticsShareRef(BaseModel):
    """The share an analytics report is about."""
    slug: str
    title: str | None = None
    filename: str | None = None


class ViewTimeSeriesPoint(BaseModel):
    date: dt.date
    views: int = 0
    unique_views: int = 0


class ReferrerBreakdown(BaseModel):
    referrer_source: str
    views: int = 0


class GeoBreakdown(BaseModel):
    country_code: str
    views: int = 0


class ShareAnalyticsResponse(BaseModel):
    share: AnalyticsShareRef
    days: int
    summary: ShareAnalytics
    timeseries: list[ViewTimeSeriesPoint]
    referrers: list[ReferrerBreakdown]
    geo: list[GeoBreakdown]
