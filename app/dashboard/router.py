"""Dashboard router — aggregates team, invite, event, share sub-routers."""

from fastapi import APIRouter

from app.dashboard.teams import router as teams_router
import app.dashboard.team_invites  # noqa: F401 — registers routes on teams_router via side-effect
from app.dashboard.invitations import (
    invitations_router,
    invite_actions_router,
)

router = APIRouter()

# Team + invites + events + shares: /api/dashboard/teams/...
router.include_router(teams_router)

# User's invitations list: /api/dashboard/invitations
router.include_router(invitations_router)

# Export invite_actions_router so main.py can mount it at /api
invite_actions = invite_actions_router
