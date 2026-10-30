"""Shared authorization check for share-mutating endpoints."""

from __future__ import annotations

from fastapi import HTTPException

from app.dependencies import User


def authorize_owner(row: dict, user: User | None, delete_token: str | None) -> None:
    """Verify the caller is the share owner or has the delete token."""
    if delete_token and row.get("delete_token") == delete_token:
        return
    if user and user.id == row.get("user_id"):
        return
    raise HTTPException(status_code=403, detail="Not authorized to modify this share")
