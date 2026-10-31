"""Profile: the signed-in user edits their own display name.

Authenticated with a Firebase token like the dashboard routes, not an API key.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from app.dependencies import User, get_current_user
from core.supabase import get_admin_client
from models.profile import ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.put("", response_model=ProfileResponse, summary="Update the caller's display name")
async def update_profile(body: ProfileUpdate, user: User = Depends(get_current_user)):
    """Set the caller's display name, creating their profile row when they have none yet."""
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("user_profiles")
        .upsert(
            {"user_id": user.id, "display_name": body.display_name},
            on_conflict="user_id",
        )
        .execute()
    )
    row = resp.data[0]
    return ProfileResponse(display_name=row["display_name"], avatar_url=row.get("avatar_url"))
