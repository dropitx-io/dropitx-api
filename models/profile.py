"""Pydantic models for the signed-in user's own profile."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ProfileUpdate(BaseModel):
    """Body of PUT /api/v1/profile."""
    display_name: str = Field(min_length=1, max_length=100)

    @field_validator("display_name", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProfileResponse(BaseModel):
    """The profile fields the caller may read back after an update: nothing else leaves the row."""
    display_name: str
    avatar_url: str | None = None
