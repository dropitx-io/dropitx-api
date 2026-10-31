"""Shared authorization check for share-mutating endpoints."""

from __future__ import annotations

from fastapi import HTTPException

from app.dependencies import User


def authorize_owner(row: dict, user: User | None, delete_token: str | None) -> None:
    """Verify the caller is the share owner or has the delete token.

    A caller who fails this check gets the missing-slug 404 for a private share, so a
    wrong token cannot tell a private share from a nonexistent one; a public share is
    already visible to everyone and answers 403.
    """
    if delete_token and row.get("delete_token") == delete_token:
        return
    if user and user.id == row.get("user_id"):
        return
    if row.get("is_private"):
        raise HTTPException(status_code=404, detail="Share not found")
    raise HTTPException(status_code=403, detail="Not authorized to modify this share")


def can_view_share(row: dict, user: User | None) -> bool:
    """A private share is visible to its owner only; everything else is visible to all."""
    if not row.get("is_private"):
        return True
    return user is not None and user.id == row.get("user_id")


def require_share_visible(row: dict, user: User | None) -> None:
    """Raise 404 (identical to a missing share) when `user` may not view this share."""
    if not can_view_share(row, user):
        raise HTTPException(status_code=404, detail="Share not found")
