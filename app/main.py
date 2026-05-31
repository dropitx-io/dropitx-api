import asyncio
import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.exceptions import ErrorResponse, RateLimitError, ShareNotFoundError, SharePasswordRequired
from core.logging_config import request_id_var, setup_logging
from core.middleware import RequestTrackingMiddleware, SecurityHeadersMiddleware

# ---------------------------------------------------------------------------
# Structured logging (JSON in production, readable in dev)
# ---------------------------------------------------------------------------
ENV = os.getenv("ENV", "production")
setup_logging(
    level=os.getenv("LOG_LEVEL", "INFO"),
    json_format=ENV == "production",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App metadata
# ---------------------------------------------------------------------------
_tags_metadata = [
    {"name": "Health", "description": "Health check endpoints (liveness + deep)."},
    {"name": "Documents", "description": "Document CRUD operations. Authenticated via API key (`shk_` / `sht_` prefix)."},
    {"name": "API Keys", "description": "Create, list, and revoke API keys. Authenticated via JWT."},
    {"name": "Teams", "description": "Team and member management. Authenticated via JWT."},
    {"name": "Custom Domains", "description": "Custom domain configuration for teams. Authenticated via JWT."},
    {"name": "Team Invites", "description": "Team invitation lifecycle — create, list, revoke, resend, bulk invite."},
    {"name": "Team Events & Shares", "description": "Audit events and shared content within a team."},
    {"name": "Invitations", "description": "List, accept, and decline invitations received by the current user."},
    {"name": "Upload", "description": "Upload HTML/Markdown files for sharing. Optional JWT auth."},
    {"name": "Download", "description": "Bulk download endpoints — ZIP archives for file groups."},
    {"name": "Publish", "description": "Publish editor content as a shareable URL. Requires JWT."},
    {"name": "Images", "description": "Upload embedded images for the editor. Requires JWT."},
    {"name": "Shares", "description": "Public share operations — view content, delete, password protect, unlock."},
    {"name": "Encryption", "description": "E2E encryption for shares — AES-256-GCM, PBKDF2 key derivation, password-based encryption. Zero-knowledge model."},
    {"name": "Search", "description": "Public full-text search across shares."},
    {"name": "Analytics", "description": "Anonymous view tracking. Always returns 200."},
    {"name": "oEmbed", "description": "oEmbed discovery endpoint for share embedding."},
    {"name": "Preview", "description": "File preview before download — images, PDF, code, markdown, video/audio, text."},
    {"name": "Explore", "description": "Public gallery — discover trending shares, filter by tags."},
    {"name": "Stars", "description": "Star/unstar public shares. Requires JWT for starring."},
    {"name": "Profiles", "description": "Public user profiles and their shared content."},
    {"name": "File Requests", "description": "Create request links that let others upload files to you. Inspired by WeTransfer 'Transfer to me'."},
]

app = FastAPI(
    title="DropItX API",
    description=(
        "Backend for DropItX — a file and text sharing platform with team collaboration.\n\n"
        "**Authentication methods:**\n"
        "- **JWT (Supabase Auth):** `Authorization: Bearer *** — used for dashboard, upload, publish, and image endpoints\n"
        "- **API Key:** `Authorization: Bearer *** or `sht_...` — used for v1 document endpoints\n\n"
        "**Rate limiting:**\n"
        "- Upload/publish: per-IP, configurable\n"
        "- Analytics: 60/min per IP (fail-open)\n"
        "- oEmbed: 60/min per IP (fail-open)\n"
        "- Password unlock: 5 per 10min per IP+slug"
    ),
    version="0.3.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=_tags_metadata,
    contact={"name": "DropItX", "url": "https://dropitx.com"},
    license_info={"name": "Private"},
)

# ---------------------------------------------------------------------------
# Middleware (order matters — last added = first executed)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins if settings.allowed_origins != "*" else ["*"],
    allow_credentials=settings.allowed_origins != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestTrackingMiddleware)

# ---------------------------------------------------------------------------
# Exception handlers — consistent error envelope
# ---------------------------------------------------------------------------

@app.exception_handler(RateLimitError)
async def _rate_limit_handler(request: Request, exc: RateLimitError):
    return JSONResponse(
        status_code=429,
        content=ErrorResponse(
            error="rate_limit_exceeded",
            detail=f"Too many requests. Retry after {exc.retry_after}s.",
            request_id=request_id_var.get(""),
        ).model_dump(),
        headers={"retry-after": str(exc.retry_after)},
    )


@app.exception_handler(ShareNotFoundError)
async def _share_not_found_handler(request: Request, exc: ShareNotFoundError):
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error="not_found",
            detail="Share not found",
            request_id=request_id_var.get(""),
        ).model_dump(),
    )


@app.exception_handler(SharePasswordRequired)
async def _share_password_handler(request: Request, exc: SharePasswordRequired):
    return JSONResponse(
        status_code=403,
        content=ErrorResponse(
            error="password_required",
            detail="This share is password-protected.",
            request_id=request_id_var.get(""),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_error",
            detail="An unexpected error occurred.",
            request_id=request_id_var.get(""),
        ).model_dump(),
    )

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from app.v1.router import router as v1_router
from app.dashboard.router import router as dashboard_router, invite_actions
from app.public.router import router as public_router
from app.internal.router import router as internal_router

app.include_router(v1_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/dashboard")
app.include_router(invite_actions, prefix="/api")
app.include_router(public_router, prefix="/api")
app.include_router(internal_router, prefix="/api")

# ---------------------------------------------------------------------------
# Background cleanup service
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def start_cleanup_service():
    """Start the background cleanup loop for expired shares and old revisions."""
    from app.services.cleanup import run_cleanup_loop
    asyncio.create_task(run_cleanup_loop())
    logger.info("Background cleanup service started")

# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Health"])
async def health_check():
    """Basic liveness probe — always returns ok if the process is alive."""
    return {"status": "ok", "service": "dropitx-api"}


@app.get("/health/deep", tags=["Health"])
async def deep_health_check():
    """Deep health probe — verifies Supabase database connectivity and latency."""
    from core.supabase import get_admin_client

    checks: dict = {}
    overall_healthy = True

    # Database check
    try:
        client = get_admin_client()
        start = time.perf_counter()
        await asyncio.to_thread(
            lambda: client.table("shares").select("id").limit(1).execute()
        )
        checks["database"] = {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        }
    except Exception as e:
        checks["database"] = {"status": "error", "error": str(e)}
        overall_healthy = False

    return {
        "status": "ok" if overall_healthy else "degraded",
        "checks": checks,
        "service": "dropitx-api",
    }
