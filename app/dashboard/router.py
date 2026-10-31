"""Dashboard router — aggregates team, invite, event, tag, folder sub-routers."""

from fastapi import APIRouter

from app.dashboard.shares import router as shares_router
from app.dashboard.teams import router as teams_router
import app.dashboard.team_invites  # noqa: F401 — registers routes on teams_router via side-effect
from app.dashboard.domains import router as domains_router
from app.dashboard.invitations import (
    invitations_router,
    invite_actions_router,
)

router = APIRouter()

router.include_router(shares_router)
router.include_router(teams_router)
router.include_router(domains_router)
router.include_router(invitations_router)

# Export invite_actions_router so main.py can mount it at /api
invite_actions = invite_actions_router
