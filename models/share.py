"""Pydantic models for the Share entity — create, update, response, search."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Database row shape (read)
# ---------------------------------------------------------------------------

class ShareBase(BaseModel):
    """Fields that exist on a share row in Supabase."""
    slug: str
    filename: str
    storage_path: str
    content_text: str | None = None
    file_size: int | None = None
    mime_type: str
    delete_token: str
    user_id: str | None = None
    title: str | None = None
    custom_slug: str | None = None
    source: str | None = None
    is_private: bool = False
    password_hash: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    view_count: int = 0
    # E2E encryption
    encrypted: bool = False
    encryption_iv: str | None = None
    encryption_salt: str | None = None
    # Burn after reading
    burn_after_reading: bool = False
    # Download limit (A3)
    max_downloads: int | None = None
    download_count: int = 0
    # Group (A1)
    group_id: str | None = None


class ShareResponse(ShareBase):
    """Share returned to the client — includes the id."""
    id: str


# ---------------------------------------------------------------------------
# Create / Update DTOs
# ---------------------------------------------------------------------------

class ShareCreate(BaseModel):
    """Payload for creating a new share."""
    content: str
    filename: str | None = None
    title: str | None = None
    custom_slug: str | None = None
    source: str | None = None
    is_private: bool = False
    password: str | None = Field(default=None, max_length=128)
    expires_in: int | None = Field(default=None, description="Seconds until expiry")
    # E2E encryption
    encrypted: bool = False
    encryption_iv: str | None = None
    encryption_salt: str | None = None
    # Burn after reading
    burn_after_reading: bool = False
    # Download limit (A3)
    max_downloads: int | None = None


class ShareUpdate(BaseModel):
    """Payload for updating an existing share."""
    content: str | None = None
    title: str | None = None
    is_private: bool | None = None
    password: str | None = Field(default=None, max_length=128)
    # E2E encryption (when updating encrypted content)
    encryption_iv: str | None = None
    encryption_salt: str | None = None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    """A single search result row."""
    slug: str
    filename: str
    created_at: datetime
    view_count: int
    expires_at: datetime | None = None
    snippet: str
    rank: float


# ---------------------------------------------------------------------------
# Version History
# ---------------------------------------------------------------------------

class ShareRevision(BaseModel):
    """A single revision snapshot."""
    id: str
    share_id: str
    revision: int
    content: str
    filename: str | None = None
    title: str | None = None
    created_at: datetime


class RevisionListResponse(BaseModel):
    """Paginated list of revisions."""
    revisions: list[ShareRevision]
    total: int
