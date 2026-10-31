"""Pydantic models for Team, TeamMember, TeamInvite, and TeamShare."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TeamRole = Literal["owner", "editor", "viewer"]
TeamPlan = Literal["free", "pro"]


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------

class Team(BaseModel):
    """A team row from Supabase."""
    id: str
    name: str
    slug: str
    plan: TeamPlan = "free"
    owner_id: str
    created_at: datetime
    updated_at: datetime


class TeamMember(BaseModel):
    """A team membership row."""
    id: str
    team_id: str
    user_id: str
    role: TeamRole
    joined_at: datetime


class TeamInvite(BaseModel):
    """A pending team invitation."""
    id: str
    team_id: str
    email: str
    role: TeamRole
    token: str
    invited_by: str
    expires_at: datetime
    created_at: datetime


class InviteLookup(BaseModel):
    """What the accept page may show to anyone holding an invite token.

    The invitee's address is set only when the signed-in caller's own address matches;
    ``email_matches`` is None for an anonymous caller.
    """
    team_name: str | None = None
    team_slug: str | None = None
    inviter_display_name: str | None = None
    role: str
    status: str
    expires_at: datetime
    invitee_email: str | None = None
    email_matches: bool | None = None


class TeamShare(BaseModel):
    """A share associated with a team."""
    id: str
    team_id: str
    share_id: str
    shared_by: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Input DTOs
# ---------------------------------------------------------------------------

class CreateTeamInput(BaseModel):
    """Payload for creating a new team."""
    name: str = Field(min_length=1, max_length=100)
    slug: str | None = Field(default=None, min_length=3, max_length=50, pattern=r"^[a-z0-9-]+$")


class CreateInviteInput(BaseModel):
    """Payload for inviting a member to a team."""
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: TeamRole
