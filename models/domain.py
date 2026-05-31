"""Pydantic models for Custom Domains."""

from __future__ import annotations
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


DomainStatus = Literal["pending", "verifying", "active", "failed"]
DomainPlan = Literal["free", "pro"]


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------

class CustomDomain(BaseModel):
    """A custom domain configured for a team."""
    id: str
    team_id: str
    domain: str
    status: DomainStatus = "pending"
    verification_token: str | None = None
    verified_at: datetime | None = None
    ssl_status: str = "pending"
    ssl_issued_at: datetime | None = None
    brand_logo_url: str | None = None
    brand_color: str | None = None
    brand_favicon_url: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Input DTOs
# ---------------------------------------------------------------------------

class AddDomainInput(BaseModel):
    """Payload for adding a custom domain to a team."""
    domain: str = Field(
        min_length=3,
        max_length=253,
        pattern=r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)*\.[a-z]{2,}$",
        description="Domain name (e.g., files.company.com)",
    )


class UpdateDomainBrandInput(BaseModel):
    """Payload for updating domain brand customization."""
    brand_logo_url: str | None = Field(default=None, max_length=2048)
    brand_color: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Hex color code (e.g., #FF5701)",
    )
    brand_favicon_url: str | None = Field(default=None, max_length=2048)


class DomainVerificationStatus(BaseModel):
    """Response for domain verification check."""
    domain: str
    status: DomainStatus
    txt_record: str | None = None
    verified_at: datetime | None = None
    ssl_status: str
    ssl_issued_at: datetime | None = None
    message: str
