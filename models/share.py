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
    # One-time download (file.io style)
    one_time_download: bool = False
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
    # One-time download (file.io style)
    one_time_download: bool = False


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
# Public metadata (GET /shares/{slug})
# ---------------------------------------------------------------------------

class GroupFile(BaseModel):
    """A sibling share in the same group, as listed on a share page."""
    slug: str
    filename: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    download_count: int = 0
    max_downloads: int | None = None

    @classmethod
    def from_row(cls, row: dict) -> GroupFile:
        return cls(
            slug=row["slug"],
            filename=row.get("filename"),
            mime_type=row.get("mime_type"),
            file_size=row.get("file_size"),
            download_count=row.get("download_count") or 0,
            max_downloads=row.get("max_downloads"),
        )


class ShareMeta(BaseModel):
    """Share metadata and access state. Built field by field from a row, never dumped from it."""
    id: str
    slug: str
    filename: str | None = None
    title: str | None = None
    mime_type: str | None = None
    language: str | None = None
    file_size: int | None = None
    view_count: int = 0
    created_at: datetime
    expires_at: datetime | None = None
    is_private: bool = False
    has_password: bool = False
    burn_after_reading: bool = False
    burned: bool = False
    encrypted: bool = False
    is_owner: bool = False
    group_id: str | None = None
    group_files: list[GroupFile] = []

    @classmethod
    def from_row(
        cls, row: dict, *, is_owner: bool, group_files: list[GroupFile] | None = None
    ) -> ShareMeta:
        return cls(
            id=str(row["id"]),
            slug=row["slug"],
            filename=row.get("filename"),
            title=row.get("title"),
            mime_type=row.get("mime_type"),
            language=row.get("language"),
            file_size=row.get("file_size"),
            view_count=row.get("view_count") or 0,
            created_at=row["created_at"],
            expires_at=row.get("expires_at"),
            is_private=bool(row.get("is_private")),
            has_password=bool(row.get("password_hash")),
            burn_after_reading=bool(row.get("burn_after_reading")),
            burned=bool(row.get("burned")),
            encrypted=bool(row.get("encrypted")),
            is_owner=is_owner,
            group_id=row.get("group_id"),
            group_files=group_files or [],
        )


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
    snippet: str = ""
    rank: float = 0.0


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
