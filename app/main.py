from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from app.v1.router import router as v1_router
from app.dashboard.router import router as dashboard_router, invite_actions
from app.public.router import router as public_router
from app.internal.router import router as internal_router

_tags_metadata = [
    {
        "name": "Health",
        "description": "Health check endpoint.",
    },
    {
        "name": "Documents",
        "description": "Document CRUD operations. Authenticated via API key (`shk_` / `sht_` prefix).",
    },
    {
        "name": "API Keys",
        "description": "Create, list, and revoke API keys. Authenticated via JWT.",
    },
    {
        "name": "Teams",
        "description": "Team and member management. Authenticated via JWT.",
    },
    {
        "name": "Team Invites",
        "description": "Team invitation lifecycle — create, list, revoke, resend, bulk invite.",
    },
    {
        "name": "Team Events & Shares",
        "description": "Audit events and shared content within a team.",
    },
    {
        "name": "Invitations",
        "description": "List, accept, and decline invitations received by the current user.",
    },
    {
        "name": "Upload",
        "description": "Upload HTML/Markdown files for sharing. Optional JWT auth.",
    },
    {
        "name": "Publish",
        "description": "Publish editor content as a shareable URL. Requires JWT.",
    },
    {
        "name": "Images",
        "description": "Upload embedded images for the editor. Requires JWT.",
    },
    {
        "name": "Shares",
        "description": "Public share operations — delete, password protect, unlock.",
    },
    {
        "name": "Search",
        "description": "Public full-text search across shares.",
    },
    {
        "name": "Analytics",
        "description": "Anonymous view tracking. Always returns 200.",
    },
    {
        "name": "oEmbed",
        "description": "oEmbed discovery endpoint for share embedding.",
    },
]

app = FastAPI(
    title="DropItX API",
    description=(
        "Backend for DropItX — a file and text sharing platform with team collaboration.\n\n"
        "**Authentication methods:**\n"
        "- **JWT (Supabase Auth):** `Authorization: Bearer <jwt>` — used for dashboard, upload, publish, and image endpoints\n"
        "- **API Key:** `Authorization: Bearer shk_...` or `sht_...` — used for v1 document endpoints\n\n"
        "**Rate limiting:**\n"
        "- Upload/publish: per-IP, configurable\n"
        "- Analytics: 60/min per IP (fail-open)\n"
        "- oEmbed: 60/min per IP (fail-open)\n"
        "- Password unlock: 5 per 10min per IP+slug"
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=_tags_metadata,
    contact={"name": "DropItX", "url": "https://dropitx.com"},
    license_info={"name": "Private"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/dashboard")
app.include_router(invite_actions, prefix="/api")
app.include_router(public_router, prefix="/api")
app.include_router(internal_router, prefix="/api")


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}
