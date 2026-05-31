"""File Request endpoints — create request links, list uploads (JWT-protected)."""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import HTTPException as HTTPExc

from app.dependencies import User, get_current_user
from core.config import settings
from core.nanoid import generate_slug
from core.supabase import get_admin_client
from models.file_request import (
    FileRequestCreate,
    FileRequestResponse,
    FileRequestUploadList,
    FileRequestUploadResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Expiration options (seconds)
_EXPIRATION_OPTIONS: dict[str, int] = {
    "1h": 3600,
    "24h": 86400,
    "7d": 604800,
    "30d": 2592000,
}
_DEFAULT_EXPIRATION = 604800  # 7 days


def _resolve_expiration(expires_in: str) -> int:
    """Resolve expiration string to seconds."""
    expires_in = expires_in.strip()
    if expires_in in _EXPIRATION_OPTIONS:
        return _EXPIRATION_OPTIONS[expires_in]
    try:
        val = int(expires_in)
        if val < 60:
            raise HTTPExc(status_code=400, detail="Minimum expiration is 60 seconds")
        if val > _EXPIRATION_OPTIONS["30d"]:
            raise HTTPExc(status_code=400, detail="Maximum expiration is 30 days")
        return val
    except ValueError:
        raise HTTPExc(
            status_code=400,
            detail=f"Invalid expires_in. Use: {', '.join(_EXPIRATION_OPTIONS.keys())} or seconds as integer.",
        )


@router.post("/requests", tags=["File Requests"], summary="Create a file request link")
async def create_file_request(
    body: FileRequestCreate,
    user: User = Depends(get_current_user),
) -> dict:
    """Create a file request link. Others can upload files to you via this link."""
    client = get_admin_client()
    slug = generate_slug()

    expires_seconds = _resolve_expiration(body.expires_in)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)).isoformat()

    row_data = {
        "slug": slug,
        "user_id": user.id,
        "title": body.title,
        "description": body.description,
        "max_files": body.max_files,
        "max_file_size_mb": body.max_file_size_mb,
        "expires_at": expires_at,
        "require_name": body.require_name,
        "require_email": body.require_email,
    }

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("file_requests").insert(row_data).execute(),
        )
    except Exception as exc:
        logger.error("Failed to create file request: %s", exc)
        raise HTTPExc(status_code=500, detail="Failed to create file request") from exc

    row = resp.data[0] if resp.data else row_data
    share_url = f"{settings.frontend_url}/r/{slug}"

    return {
        "id": row.get("id", ""),
        "slug": slug,
        "title": body.title,
        "description": body.description,
        "max_files": body.max_files,
        "max_file_size_mb": body.max_file_size_mb,
        "expires_at": expires_at,
        "require_name": body.require_name,
        "require_email": body.require_email,
        "is_active": True,
        "upload_count": 0,
        "total_size_bytes": 0,
        "created_at": row.get("created_at", ""),
        "share_url": share_url,
    }


@router.get("/dashboard/requests", tags=["File Requests"], summary="List my file requests")
async def list_my_requests(
    user: User = Depends(get_current_user),
) -> list[dict]:
    """List all file requests created by the current user."""
    client = get_admin_client()

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("file_requests")
            .select("*")
            .eq("user_id", user.id)
            .order("created_at", desc=True)
            .execute(),
        )
    except Exception as exc:
        logger.error("Failed to list file requests: %s", exc)
        raise HTTPExc(status_code=500, detail="Failed to list file requests") from exc

    rows = resp.data or []
    results = []
    for row in rows:
        results.append({
            "id": row["id"],
            "slug": row["slug"],
            "title": row.get("title"),
            "description": row.get("description"),
            "max_files": row["max_files"],
            "max_file_size_mb": row["max_file_size_mb"],
            "expires_at": row["expires_at"],
            "require_name": row["require_name"],
            "require_email": row["require_email"],
            "is_active": row["is_active"],
            "upload_count": row["upload_count"],
            "total_size_bytes": row["total_size_bytes"],
            "created_at": row["created_at"],
            "share_url": f"{settings.frontend_url}/r/{row['slug']}",
        })

    return results


@router.get("/dashboard/requests/{request_id}/uploads", tags=["File Requests"], summary="Get uploads for a request")
async def get_request_uploads(
    request_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Get all uploads submitted to a specific file request."""
    client = get_admin_client()

    # Verify ownership and get request info
    req_resp = await asyncio.to_thread(
        lambda: client.table("file_requests")
        .select("id, slug, title, max_files, upload_count, total_size_bytes")
        .eq("id", request_id)
        .eq("user_id", user.id)
        .execute(),
    )
    if not req_resp.data:
        raise HTTPExc(status_code=404, detail="File request not found")

    request_row = req_resp.data[0]

    # Get uploads
    uploads_resp = await asyncio.to_thread(
        lambda: client.table("file_request_uploads")
        .select("*")
        .eq("file_request_id", request_id)
        .order("created_at", desc=True)
        .execute(),
    )

    uploads = uploads_resp.data or []
    return {
        "request": {
            "id": request_row["id"],
            "slug": request_row["slug"],
            "title": request_row.get("title"),
            "max_files": request_row["max_files"],
            "upload_count": request_row["upload_count"],
            "total_size_bytes": request_row["total_size_bytes"],
        },
        "uploads": [
            {
                "id": u["id"],
                "filename": u["filename"],
                "file_size": u["file_size"],
                "mime_type": u["mime_type"],
                "uploader_name": u.get("uploader_name"),
                "uploader_email": u.get("uploader_email"),
                "created_at": u["created_at"],
            }
            for u in uploads
        ],
        "total": len(uploads),
    }


@router.patch("/dashboard/requests/{request_id}", tags=["File Requests"], summary="Update a file request")
async def update_file_request(
    request_id: str,
    body: dict,
    user: User = Depends(get_current_user),
) -> dict:
    """Update a file request (title, description, limits, active status)."""
    client = get_admin_client()

    # Verify ownership
    req_resp = await asyncio.to_thread(
        lambda: client.table("file_requests")
        .select("id")
        .eq("id", request_id)
        .eq("user_id", user.id)
        .execute(),
    )
    if not req_resp.data:
        raise HTTPExc(status_code=404, detail="File request not found")

    # Allowed update fields
    allowed = {"title", "description", "is_active", "max_files", "max_file_size_mb", "require_name", "require_email"}
    update_data = {k: v for k, v in body.items() if k in allowed}
    if not update_data:
        raise HTTPExc(status_code=400, detail="No valid fields to update")

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("file_requests")
            .update(update_data)
            .eq("id", request_id)
            .execute(),
        )
    except Exception as exc:
        logger.error("Failed to update file request %s: %s", request_id, exc)
        raise HTTPExc(status_code=500, detail="Failed to update file request") from exc

    row = resp.data[0] if resp.data else {}
    return {
        "id": row.get("id", request_id),
        "slug": row.get("slug", ""),
        "title": row.get("title"),
        "is_active": row.get("is_active"),
        "updated": True,
    }


@router.delete("/dashboard/requests/{request_id}", tags=["File Requests"], summary="Delete a file request")
async def delete_file_request(
    request_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Delete a file request and all its uploads."""
    client = get_admin_client()

    # Verify ownership
    req_resp = await asyncio.to_thread(
        lambda: client.table("file_requests")
        .select("id, slug")
        .eq("id", request_id)
        .eq("user_id", user.id)
        .execute(),
    )
    if not req_resp.data:
        raise HTTPExc(status_code=404, detail="File request not found")

    # Delete uploads first (storage cleanup)
    uploads_resp = await asyncio.to_thread(
        lambda: client.table("file_request_uploads")
        .select("storage_path")
        .eq("file_request_id", request_id)
        .execute(),
    )
    for upload in uploads_resp.data or []:
        try:
            await asyncio.to_thread(
                lambda sp=upload["storage_path"]: client.storage.from_("html-files").remove([sp]),
            )
        except Exception:
            logger.warning("Failed to cleanup storage for upload %s", upload.get("storage_path"))

    # Delete request (cascades to uploads via FK)
    await asyncio.to_thread(
        lambda: client.table("file_requests").delete().eq("id", request_id).execute(),
    )

    return {"deleted": True, "id": request_id}
