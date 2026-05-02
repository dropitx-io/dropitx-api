"""Pydantic models for analytics tracking and share stats."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyticsTrack(BaseModel):
    """Payload for tracking a share view event."""
    tracking_token: str = Field(min_length=1)
    share_id: str = Field(min_length=1)
    referrer: str | None = None
    is_embed: bool = False


class ShareAnalytics(BaseModel):
    """Aggregate analytics for a share."""
    total_views: int = 0
    unique_views: int = 0
    views_today: int = 0
    views_7d: int = 0
    avg_daily_views: float = 0.0
