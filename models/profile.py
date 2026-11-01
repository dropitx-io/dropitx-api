"""Pydantic models for the signed-in user's own profile."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from core.usernames import validate_username


class ProfileUpdate(BaseModel):
    """Body of PUT /api/v1/profile. An omitted optional field is left as it is."""
    display_name: str = Field(min_length=1, max_length=100)
    username: str | None = None
    is_public: bool | None = None

    @field_validator("display_name", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("username", mode="before")
    @classmethod
    def _normalize_username(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("username")
    @classmethod
    def _valid_username(cls, value):
        if value is not None and (error := validate_username(value)):
            raise ValueError(error)
        return value


class ProfileResponse(BaseModel):
    """The profile fields the caller may read back after an update: nothing else leaves the row."""
    display_name: str
    avatar_url: str | None = None
    username: str | None = None
    is_public: bool = False
