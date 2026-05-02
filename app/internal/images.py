"""Image upload endpoint — for editor-embedded images."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, UploadFile
from fastapi.exceptions import HTTPException

from app.dependencies import User, get_current_user
from core.config import settings
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()

# Allowed image MIME types
_ALLOWED_TYPES: set[str] = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}

# Extension mapping for allowed types
_EXT_MAP: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

_MAX_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("/images/upload", tags=["Images"])
async def upload_image(
    file: UploadFile,
    user: User = Depends(get_current_user),
) -> dict:
    """Upload an image for use in the editor. Requires authentication."""
    # Validate content type
    content_type = (file.content_type or "").lower().split(";")[0].strip()
    if content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid image type. Allowed: PNG, JPG, GIF, WebP.",
        )

    # Read and validate size
    content_bytes = await file.read()
    if len(content_bytes) > _MAX_SIZE:
        raise HTTPException(
            status_code=400, detail="Image too large. Maximum size is 5 MB."
        )
    if len(content_bytes) == 0:
        raise HTTPException(status_code=400, detail="Image is empty.")

    # Build storage path: uploads/{userId}/{filename}
    filename = file.filename or f"image{_EXT_MAP[content_type]}"
    storage_path = f"uploads/{user.id}/{filename}"

    # Upload to Supabase Storage
    client = get_admin_client()
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").upload(
                storage_path,
                content_bytes,
                content_type=content_type,
                upsert=True,
            ),
        )
    except Exception as exc:
        logger.error("Image upload failed for user=%s: %s", user.id, exc)
        raise HTTPException(status_code=500, detail="Failed to upload image") from exc

    # Get public URL
    public_url = (
        f"{settings.supabase_url}/storage/v1/object/public/html-files/{storage_path}"
    )

    return {"url": public_url, "filename": filename}
