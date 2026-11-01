"""Profile: the signed-in user edits their own display name, username and visibility.

Authenticated with a Firebase token like the dashboard routes, not an API key.
"""

from __future__ import annotations

import asyncio

from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import User, get_current_user
from core.supabase import get_admin_client
from models.profile import ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["Profile"])

_USERNAME_TAKEN = "Username is already taken"


@router.put("", response_model=ProfileResponse, summary="Update the caller's profile")
async def update_profile(body: ProfileUpdate, user: User = Depends(get_current_user)):
    """Set the caller's display name, and optionally username and public visibility.

    Creates the profile row when the caller has none yet. 409 when another user has
    the username; 422 when it is malformed or reserved.
    """
    client = get_admin_client()
    row: dict = {"user_id": user.id, "display_name": body.display_name}
    if body.username is not None:
        taken = await asyncio.to_thread(
            lambda: client.table("user_profiles")
            .select("user_id")
            .eq("username", body.username)
            .neq("user_id", user.id)
            .execute()
        )
        if taken.data:
            raise HTTPException(status_code=409, detail=_USERNAME_TAKEN)
        row["username"] = body.username
    if body.is_public is not None:
        row["is_public"] = body.is_public

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("user_profiles").upsert(row, on_conflict="user_id").execute()
        )
    except UniqueViolationError as exc:
        # Taken between the check and the write.
        raise HTTPException(status_code=409, detail=_USERNAME_TAKEN) from exc
    saved = resp.data[0]
    return ProfileResponse(
        display_name=saved["display_name"],
        avatar_url=saved.get("avatar_url"),
        username=saved.get("username"),
        is_public=bool(saved.get("is_public")),
    )
