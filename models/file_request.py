"""Pydantic models for File Request Links (WeTransfer-style 'Transfer to me')."""

from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Create / Update DTOs
# ---------------------------------------------------------------------------

class FileRequestCreate(BaseModel):
    """Payload for creating a file request link."""
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    max_files: int = Field(default=10, ge=1, le=100, description="Max number of files allowed")
    max_file_size_mb: int = Field(default=100, ge=1, le=2000, description="Max size per file in MB")
    expires_in: str = Field(
        default="7d",
        description="Expiration: '1h', '24h', '7d', '30d', or seconds as integer",
    )
    require_name: bool = Field(default=False, description="Require uploader name")
    require_email: bool = Field(default=False, description="Require uploader email")


class FileRequestUpdate(BaseModel):
    """Payload for updating an existing file request."""
    title: str | None = None
    description: str | None = None
    is_active: bool | None = None
    max_files: int | None = Field(default=None, ge=1, le=100)
    max_file_size_mb: int | None = Field(default=None, ge=1, le=2000)
    require_name: bool | None = None
    require_email: bool | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class FileRequestResponse(BaseModel):
    """File request returned to the owner."""
    id: str
    slug: str
    title: str | None = None
    description: str | None = None
    max_files: int
    max_file_size_mb: int
    expires_at: datetime
    require_name: bool
    require_email: bool
    is_active: bool
    upload_count: int
    total_size_bytes: int
    created_at: datetime
    share_url: str | None = None


class FileRequestPublic(BaseModel):
    """Public view of a file request (for uploaders)."""
    id: str
    title: str | None = None
    description: str | None = None
    max_files: int
    max_file_size_mb: int
    expires_at: datetime
    require_name: bool
    require_email: bool
    upload_count: int
    is_expired: bool


class FileRequestUploadResponse(BaseModel):
    """Response after uploading a file to a request."""
    id: str
    filename: str
    file_size: int
    mime_type: str
    created_at: datetime


class FileRequestUploadList(BaseModel):
    """Uploads for a specific file request."""
    uploads: list[FileRequestUploadResponse]
    total: int
    total_size_bytes: int


class FileRequestUploadSubmit(BaseModel):
    """Metadata submitted alongside an anonymous upload."""
    uploader_name: str | None = Field(default=None, max_length=200)
    uploader_email: str | None = Field(default=None, max_length=300)
