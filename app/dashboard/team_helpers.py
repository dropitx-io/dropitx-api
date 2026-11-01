"""Shared helpers for dashboard team endpoints — role checks, team lookups, invite utilities."""

from __future__ import annotations

import asyncio
import json
import secrets
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from core.supabase import get_admin_client
from models.team import TeamRole

logger = logging.getLogger(__name__)

# Role hierarchy: numeric weight for comparison
ROLE_WEIGHT: dict[TeamRole, int] = {
    "owner": 3,
    "editor": 2,
    "viewer": 1,
}


async def resolve_team_by_slug(slug: str) -> dict | None:
    """Look up a team row by slug. Returns the raw dict or None."""
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("teams")
        .select("*")
        .eq("slug", slug)
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


async def require_team_member(
    user_id: str,
    team_id: str,
    min_role: TeamRole = "viewer",
) -> dict:
    """Verify that *user_id* is a member of *team_id* with at least *min_role*.

    Returns the membership row dict on success.
    Raises HTTPException(403) if not a member or insufficient role.
    """
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("team_members")
        .select("*")
        .eq("team_id", team_id)
        .eq("user_id", user_id)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=403, detail="Not a team member")

    membership = rows[0]
    member_role: str = membership["role"]
    if ROLE_WEIGHT.get(member_role, 0) < ROLE_WEIGHT[min_role]:
        raise HTTPException(
            status_code=403,
            detail=f"Requires {min_role} role or higher",
        )
    return membership


def generate_invite_token() -> str:
    """Generate a 32-byte hex token for team invitations."""
    return secrets.token_hex(32)


def get_invite_expiry() -> str:
    """ISO-8601 timestamp 7 days from now (UTC)."""
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    return expires.isoformat()


async def record_team_event(team_id: str, actor_id: str | None, event_type: str, payload: dict) -> None:
    """Append an event to a team's activity feed.

    Best-effort: a failed write is logged and never fails the action it records.
    """
    client = get_admin_client()
    try:
        await asyncio.to_thread(
            lambda: client.table("team_events").insert({
                "team_id": team_id,
                "user_id": actor_id,
                "event_type": event_type,
                "payload": json.dumps(payload),
            }).execute()
        )
    except Exception:
        logger.warning("Failed to record %s event for team %s", event_type, team_id, exc_info=True)


async def record_share_removed(share: dict, actor_id: str | None) -> None:
    """Record share.removed in every team the share belongs to. Call before the share is deleted."""
    client = get_admin_client()
    try:
        links = await asyncio.to_thread(
            lambda: client.table("team_shares").select("team_id").eq("share_id", share["id"]).execute()
        )
    except Exception:
        logger.warning("Failed to look up the teams of share %s", share.get("slug"), exc_info=True)
        return
    for team_id in {link["team_id"] for link in links.data or []}:
        await record_team_event(
            team_id, actor_id, "share.removed", {"share_id": share["id"], "slug": share["slug"]},
        )
