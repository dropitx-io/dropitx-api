"""Team invite, event, and share endpoints.

Registers routes on the same router as teams.py to share the /teams prefix.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import User, get_current_user
from app.dashboard.team_helpers import (
    generate_invite_token,
    get_invite_expiry,
    require_team_member,
    resolve_team_by_slug,
)
from core.config import settings
from core.supabase import get_admin_client
from models.team import TeamRole

logger = logging.getLogger(__name__)

# Shared router — imported from teams module so all /teams/* routes live on one router
from app.dashboard.teams import router  # noqa: E402


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------

@router.get("/teams/{slug}/invites", tags=["Team Invites"])
async def list_invites(slug: str, user: User = Depends(get_current_user)):
    """List pending invites for a team."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"])

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("team_invites")
        .select("*")
        .eq("team_id", team["id"])
        .execute()
    )
    return resp.data or []


@router.post("/teams/{slug}/invites", status_code=201, tags=["Team Invites"])
async def create_invite(
    slug: str,
    body: dict,
    user: User = Depends(get_current_user),
):
    """Create a team invite. Editor+."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"], min_role="editor")

    email = body.get("email")
    role: TeamRole = body.get("role", "viewer")
    if not email:
        raise HTTPException(status_code=422, detail="email required")

    token = generate_invite_token()
    expiry = get_invite_expiry()

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.rpc("create_team_invite", {
            "p_team_id": team["id"],
            "p_email": email,
            "p_role": role,
            "p_token": token,
            "p_invited_by": user.id,
            "p_expires_at": expiry,
        }).execute()
    )

    invite_url = f"{settings.frontend_url}/invite/{token}"
    result = resp.data if isinstance(resp.data, dict) else {"token": token}
    return {**result, "invite_url": invite_url}


@router.delete("/teams/{slug}/invites", tags=["Team Invites"])
async def revoke_invite(
    slug: str,
    body: dict,
    user: User = Depends(get_current_user),
):
    """Revoke a pending invite. Editor+."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"], min_role="editor")

    invite_id = body.get("invite_id")
    if not invite_id:
        raise HTTPException(status_code=422, detail="invite_id required")

    client = get_admin_client()
    await asyncio.to_thread(
        lambda: client.table("team_invites")
        .delete()
        .eq("id", invite_id)
        .eq("team_id", team["id"])
        .execute()
    )
    return {"detail": "Invite revoked"}


@router.post("/teams/{slug}/invites/bulk", tags=["Team Invites"])
async def bulk_invite(
    slug: str,
    body: dict,
    user: User = Depends(get_current_user),
):
    """Bulk invite up to 50 emails. Editor+."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"], min_role="editor")

    emails: list[str] = body.get("emails", [])
    role: TeamRole = body.get("role", "viewer")

    if len(emails) > 50:
        raise HTTPException(status_code=422, detail="Max 50 emails per request")

    success, duplicate, errors = 0, 0, 0
    client = get_admin_client()

    for email in emails:
        token = generate_invite_token()
        expiry = get_invite_expiry()
        try:
            await asyncio.to_thread(
                lambda e=email, t=token: client.rpc("create_team_invite", {
                    "p_team_id": team["id"],
                    "p_email": e,
                    "p_role": role,
                    "p_token": t,
                    "p_invited_by": user.id,
                    "p_expires_at": expiry,
                }).execute()
            )
            success += 1
        except Exception as exc:
            msg = str(exc).lower()
            if "duplicate" in msg or "unique" in msg or "already" in msg:
                duplicate += 1
            else:
                logger.warning("Bulk invite error for %s: %s", email, exc)
                errors += 1

    return {"success": success, "duplicate": duplicate, "errors": errors}


@router.post("/teams/{slug}/invites/{invite_id}/resend", tags=["Team Invites"])
async def resend_invite(
    slug: str,
    invite_id: str,
    user: User = Depends(get_current_user),
):
    """Resend an invite. If expired, generate new token and expiry. Editor+."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"], min_role="editor")

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("team_invites")
        .select("*")
        .eq("id", invite_id)
        .eq("team_id", team["id"])
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Invite not found")

    invite = rows[0]
    updates: dict = {}

    expires_at = invite.get("expires_at")
    if expires_at and datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
        updates["token"] = generate_invite_token()
        updates["expires_at"] = get_invite_expiry()

    if updates:
        await asyncio.to_thread(
            lambda: client.table("team_invites")
            .update(updates)
            .eq("id", invite_id)
            .execute()
        )

    return {"detail": "Invite resent"}


# ---------------------------------------------------------------------------
# Events & Shares
# ---------------------------------------------------------------------------

@router.get("/teams/{slug}/events", tags=["Team Events & Shares"])
async def list_events(
    slug: str,
    user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List team events with pagination."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"])

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("team_events")
        .select("*")
        .eq("team_id", team["id"])
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return resp.data or []


@router.get("/teams/{slug}/shares", tags=["Team Events & Shares"])
async def list_shares(
    slug: str,
    user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List team shares with join to shares table. Pagination."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"])

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("team_shares")
        .select("*, shares(*)")
        .eq("team_id", team["id"])
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return resp.data or []
