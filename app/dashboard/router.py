"""Dashboard router — aggregates team, invite, event, tag, folder sub-routers."""

from fastapi import APIRouter

from app.dashboard.teams import router as teams_router
import app.dashboard.team_invites  # noqa: F401 — registers routes on teams_router via side-effect
from app.dashboard.domains import router as domains_router
from app.dashboard.invitations import (
    invitations_router,
    invite_actions_router,
)
from app.dashboard.tags import router as tags_router
from app.dashboard.folders import router as folders_router

router = APIRouter()

# Team + invites + events + shares: /api/dashboard/teams/...
router.include_router(teams_router)

# Custom domains: /api/dashboard/teams/{slug}/domains
router.include_router(domains_router)

# User's invitations list: /api/dashboard/invitations
router.include_router(invitations_router)

# Tags: /api/dashboard/tags/...
router.include_router(tags_router)

# Folders: /api/dashboard/folders/...
router.include_router(folders_router)

# Export invite_actions_router so main.py can mount it at /api
invite_actions = invite_actions_router
