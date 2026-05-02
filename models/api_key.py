"""Pydantic models for API key management."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    """Payload for creating a new API key."""
    name: str = Field(min_length=1, max_length=100)
    team_id: str | None = None


class ApiKeyResponse(BaseModel):
    """API key returned to the client (never the full key)."""
    id: str
    name: str
    key_prefix: str
    team_id: str | None = None
    last_used_at: datetime | None = None
    created_at: datetime


class ApiKeyCreateResponse(ApiKeyResponse):
    """Returned once after creation — includes the full raw key."""
    key: str
