"""User invitation management — list, accept, decline invites.

Two routers:
  - invitations_router: /invitations (mounted under /api/dashboard)
  - invite_actions_router: /invite/accept, /invite/decline (mounted under /api)
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import User, get_current_user
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

# Router for /api/dashboard/invitations
invitations_router = APIRouter()

# Router for /api/invite/accept and /api/invite/decline
invite_actions_router = APIRouter()


@invitations_router.get("/invitations", tags=["Invitations"])
async def list_invitations(user: User = Depends(get_current_user)):
    """List pending invites matching the authenticated user's email."""
    if not user.email:
        return []

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("team_invites")
        .select("*, teams(id, name, slug), user_profiles!invited_by(id, display_name, avatar_url)")
        .eq("email", user.email)
        .execute()
    )
    return resp.data or []


@invite_actions_router.post("/invite/accept", tags=["Invitations"])
async def accept_invite(
    body: dict,
    user: User = Depends(get_current_user),
):
    """Accept a team invite by token. Calls RPC accept_team_invite."""
    token = body.get("token")
    if not token:
        raise HTTPException(status_code=422, detail="token required")

    client = get_admin_client()
    try:
        resp = await asyncio.to_thread(
            lambda: client.rpc("accept_team_invite", {
                "p_token": token,
                "p_user_id": user.id,
            }).execute()
        )
        return {"detail": "Invite accepted", "data": resp.data}
    except Exception as exc:
        logger.warning("Accept invite failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=str(exc) if "expired" in str(exc).lower() else "Failed to accept invite",
        ) from exc


@invite_actions_router.post("/invite/decline", tags=["Invitations"])
async def decline_invite(
    body: dict,
    user: User = Depends(get_current_user),
):
    """Decline a team invite by token. Calls RPC decline_team_invite."""
    token = body.get("token")
    if not token:
        raise HTTPException(status_code=422, detail="token required")

    client = get_admin_client()
    try:
        resp = await asyncio.to_thread(
            lambda: client.rpc("decline_team_invite", {
                "p_token": token,
            }).execute()
        )
        return {"detail": "Invite declined", "data": resp.data}
    except Exception as exc:
        logger.warning("Decline invite failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Failed to decline invite",
        ) from exc
