"""Team CRUD and member management endpoints."""

from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import User, get_current_user
from app.dashboard.team_helpers import require_team_member, resolve_team_by_slug
from core.supabase import get_admin_client
from models.team import CreateTeamInput

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Convert a team name into a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")[:50]


# ---------------------------------------------------------------------------
# Team CRUD
# ---------------------------------------------------------------------------

@router.get("/teams")
async def list_teams(user: User = Depends(get_current_user)):
    """List all teams the authenticated user belongs to."""
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("team_members")
        .select("team_id, role, joined_at, teams(*)")
        .eq("user_id", user.id)
        .execute()
    )
    return resp.data or []


@router.post("/teams", status_code=201)
async def create_team(
    body: CreateTeamInput,
    user: User = Depends(get_current_user),
):
    """Create a new team. Caller becomes owner."""
    slug = body.slug or _slugify(body.name)
    client = get_admin_client()

    existing = await asyncio.to_thread(
        lambda: client.table("teams").select("id").eq("slug", slug).execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="Slug already taken")

    team = await asyncio.to_thread(
        lambda: client.table("teams")
        .insert({"name": body.name, "slug": slug, "owner_id": user.id})
        .execute()
    )
    team_row = team.data[0]

    await asyncio.to_thread(
        lambda: client.table("team_members")
        .insert({"team_id": team_row["id"], "user_id": user.id, "role": "owner"})
        .execute()
    )
    return team_row


@router.get("/teams/{slug}")
async def get_team(slug: str, user: User = Depends(get_current_user)):
    """Get team details. Must be a member."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"])
    return team


@router.patch("/teams/{slug}")
async def update_team(
    slug: str,
    body: dict,
    user: User = Depends(get_current_user),
):
    """Update team name/slug. Owner only."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"], min_role="owner")

    updates = {k: body[k] for k in ("name", "slug") if k in body}
    if not updates:
        return team

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("teams").update(updates).eq("id", team["id"]).execute()
    )
    return resp.data[0]


@router.delete("/teams/{slug}", status_code=204)
async def delete_team(slug: str, user: User = Depends(get_current_user)):
    """Delete team and all associated data. Owner only."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"], min_role="owner")

    client = get_admin_client()
    await asyncio.to_thread(
        lambda: client.table("teams").delete().eq("id", team["id"]).execute()
    )


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@router.get("/teams/{slug}/members")
async def list_members(slug: str, user: User = Depends(get_current_user)):
    """List team members with display_name and avatar from user_profiles."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"])

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("team_members")
        .select("*, user_profiles!user_id(display_name, avatar_url)")
        .eq("team_id", team["id"])
        .execute()
    )
    return resp.data or []


@router.patch("/teams/{slug}/members")
async def change_member_role(
    slug: str,
    body: dict,
    user: User = Depends(get_current_user),
):
    """Change a member's role. Owner only. Uses RPC change_team_member_role."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"], min_role="owner")

    target_user_id = body.get("user_id")
    new_role = body.get("role")
    if not target_user_id or not new_role:
        raise HTTPException(status_code=422, detail="user_id and role required")

    client = get_admin_client()
    await asyncio.to_thread(
        lambda: client.rpc("change_team_member_role", {
            "p_team_id": team["id"],
            "p_user_id": target_user_id,
            "p_new_role": new_role,
        }).execute()
    )
    return {"detail": "Role updated"}


@router.delete("/teams/{slug}/members")
async def remove_member(
    slug: str,
    body: dict,
    user: User = Depends(get_current_user),
):
    """Remove a member. Can remove self, or owner removes others."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    target_user_id = body.get("user_id")
    if not target_user_id:
        raise HTTPException(status_code=422, detail="user_id required")

    if target_user_id != user.id:
        await require_team_member(user.id, team["id"], min_role="owner")
    else:
        await require_team_member(user.id, team["id"])

    client = get_admin_client()
    await asyncio.to_thread(
        lambda: client.rpc("remove_team_member", {
            "p_team_id": team["id"],
            "p_user_id": target_user_id,
        }).execute()
    )
    return {"detail": "Member removed"}
