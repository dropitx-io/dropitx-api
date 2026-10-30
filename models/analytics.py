"""Pydantic models for analytics tracking and share stats."""

from __future__ import annotations

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
