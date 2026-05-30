"""File upload endpoints — single and batch file sharing."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request, UploadFile, Form
from fastapi.exceptions import HTTPException
from pydantic import BaseModel

from app.dependencies import User, get_client_ip, get_optional_user
from core.config import settings
from core.extract_text import extract_text_from_html, extract_text_from_markdown
from core.nanoid import generate_delete_token, generate_slug
from core.rate_limit import check_upload_rate_limit
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()

# Allowed MIME types and their extensions (A2: expanded for general file support)
_ALLOWED_TYPES: dict[str, str] = {
    # Text / markup
    "text/html": "html",
    "text/htm": "html",
    "text/markdown": "md",
    "text/plain": "txt",
    # Documents
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    # Images
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
    # Video
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
    "video/x-matroska": "mkv",
    # Audio
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/flac": "flac",
    "audio/aac": "aac",
    "audio/webm": "weba",
    # Archives
    "application/zip": "zip",
    "application/x-rar-compressed": "rar",
    "application/x-7z-compressed": "7z",
    "application/gzip": "gz",
    "application/x-tar": "tar",
}

# Extension-to-content_type mapping for fallback detection
_EXT_MAP: dict[str, str] = {
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".zip": "application/zip",
    ".rar": "application/x-rar-compressed",
    ".7z": "application/x-7z-compressed",
    ".gz": "application/gzip",
    ".tar": "application/x-tar",
}

# Text-like MIME types that get text extraction for search indexing
_TEXT_TYPES: set[str] = {"text/html", "text/htm", "text/markdown", "text/plain"}

_MAX_SIZE_TEXT = 50 * 1024 * 1024    # 50 MB for text files
_MAX_SIZE_BINARY = 500 * 1024 * 1024  # 500 MB for binary files


# Expiration options (seconds)
_EXPIRATION_OPTIONS: dict[str, int] = {
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "7d": 604800,
    "30d": 2592000,
}
_DEFAULT_EXPIRATION = 2592000  # 30 days


class UploadResponse:
    """Response model for single upload endpoint."""

    def __init__(
        self,
        slug: str,
        url: str,
        filename: str,
        deleteToken: str,
        encrypted: bool = False,
        encryption_iv: str | None = None,
        encryption_salt: str | None = None,
        burn_after_reading: bool = False,
        expires_at: str | None = None,
    ):
        self.slug = slug
        self.url = url
        self.filename = filename
        self.deleteToken = deleteToken
        self.encrypted = encrypted
        self.encryption_iv = encryption_iv
        self.encryption_salt = encryption_salt
        self.burn_after_reading = burn_after_reading
        self.expires_at = expires_at

    def dict(self) -> dict:
        return {
            "slug": self.slug,
            "url": self.url,
            "filename": self.filename,
            "deleteToken": self.deleteToken,
            "encrypted": self.encrypted,
            "encryption_iv": self.encryption_iv,
            "encryption_salt": self.encryption_salt,
            "burn_after_reading": self.burn_after_reading,
            "expires_at": self.expires_at,
        }


class BatchUploadResponse(BaseModel):
    """Response model for batch upload endpoint (A1)."""
    group_slug: str
    group_url: str
    files: list[dict]


@router.post("/upload", tags=["Upload"])
async def upload(
    request: Request,
    file: UploadFile,
    user: User | None = Depends(get_optional_user),
    # Query params for optional features
    encrypted: bool = False,
    encryption_iv: str | None = None,
    encryption_salt: str | None = None,
    burn_after_reading: bool = False,
    expires_in: str | None = Form(default=None),
    max_downloads: int | None = Form(default=None),
) -> dict:
    """Upload a file. Optional auth for linking to user."""
    # Rate limit
    ip = get_client_ip(request)
    rate = await asyncio.to_thread(check_upload_rate_limit, ip)
    if not rate.success:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Validate encryption params
    if encrypted and (not encryption_iv or not encryption_salt):
        raise HTTPException(
            status_code=400,
            detail="encryption_iv and encryption_salt are required when encrypted=true",
        )

    # Validate file type
    content_type = _resolve_content_type(file)
    if not content_type:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type.",
        )

    # Read and validate size
    content_bytes = await file.read()
    is_binary = content_type not in _TEXT_TYPES
    max_size = _MAX_SIZE_BINARY if is_binary else _MAX_SIZE_TEXT
    if len(content_bytes) > max_size:
        raise HTTPException(
            status_code=400, detail=f"File too large. Maximum size is {max_size // (1024*1024)} MB."
        )
    if len(content_bytes) == 0:
        raise HTTPException(status_code=400, detail="File is empty.")

    # Validate max_downloads (A3)
    if max_downloads is not None and max_downloads < 1:
        raise HTTPException(status_code=400, detail="max_downloads must be >= 1")

    # Validate expires_in (A4)
    expires_seconds = _resolve_expiration(expires_in)

    # Generate identifiers
    slug = generate_slug()
    ext = _ALLOWED_TYPES[content_type]
    storage_path = f"shares/{slug}.{ext}"
    delete_token = generate_delete_token()

    # Upload to Supabase Storage
    client = get_admin_client()
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").upload(
                storage_path,
                content_bytes,
                file_options={"content-type": content_type, "upsert": "true"},
            ),
        )
    except Exception as exc:
        logger.error("Storage upload failed for slug=%s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to upload file") from exc

    # Extract plain text for search (only for text-based files, skip if encrypted)
    plain_text = ""
    if not encrypted and content_type in _TEXT_TYPES:
        content_str = content_bytes.decode("utf-8", errors="replace")
        if content_type in ("text/html", "text/htm"):
            plain_text = extract_text_from_html(content_str)
        else:
            plain_text = extract_text_from_markdown(content_str)

    # Insert into shares table
    share_url = f"{settings.supabase_url}/storage/v1/object/public/html-files/{storage_path}"
    filename = file.filename or f"upload.{ext}"

    # Calculate expires_at
    from datetime import datetime, timezone, timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)).isoformat()

    row_data: dict = {
        "slug": slug,
        "user_id": user.id if user else None,
        "storage_path": storage_path,
        "filename": filename,
        "title": None,
        "is_private": False,
        "delete_token": delete_token,
        "content_text": plain_text[:5000] if plain_text else None,
        "file_size": len(content_bytes),
        "mime_type": content_type,
        "source": "upload",
        "encrypted": encrypted,
        "encryption_iv": encryption_iv,
        "encryption_salt": encryption_salt,
        "burn_after_reading": burn_after_reading,
        "expires_at": expires_at,
    }
    if max_downloads is not None:
        row_data["max_downloads"] = max_downloads

    try:
        await asyncio.to_thread(
            lambda: client.table("shares").insert(row_data).execute(),
        )
    except Exception as exc:
        logger.error("DB insert failed for slug=%s: %s", slug, exc)
        await _cleanup_storage(storage_path)
        raise HTTPException(status_code=500, detail="Failed to save share") from exc

    resp = UploadResponse(
        slug=slug,
        url=share_url,
        filename=filename,
        deleteToken=delete_token,
        encrypted=encrypted,
        encryption_iv=encryption_iv,
        encryption_salt=encryption_salt,
        burn_after_reading=burn_after_reading,
        expires_at=expires_at,
    )
    return resp.dict()


@router.post("/upload/batch", tags=["Upload"])
async def upload_batch(
    request: Request,
    files: list[UploadFile],
    user: User | None = Depends(get_optional_user),
    max_downloads: int | None = Form(default=None),
    expires_in: str | None = Form(default=None),
) -> dict:
    """Upload multiple files as a group (A1). Returns group slug + individual file URLs."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 files per batch.")

    # Rate limit
    ip = get_client_ip(request)
    rate = await asyncio.to_thread(check_upload_rate_limit, ip)
    if not rate.success:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Validate max_downloads (A3)
    if max_downloads is not None and max_downloads < 1:
        raise HTTPException(status_code=400, detail="max_downloads must be >= 1")

    # Validate expires_in (A4)
    expires_seconds = _resolve_expiration(expires_in)

    client = get_admin_client()
    group_slug = generate_slug()

    # Create share_groups record (A1)
    from datetime import datetime, timezone, timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)).isoformat()

    try:
        await asyncio.to_thread(
            lambda: client.table("share_groups").insert(
                {
                    "slug": group_slug,
                    "user_id": user.id if user else None,
                }
            ).execute(),
        )
    except Exception as exc:
        logger.error("Failed to create share_group slug=%s: %s", group_slug, exc)
        raise HTTPException(status_code=500, detail="Failed to create share group") from exc

    # Upload each file
    uploaded_files: list[dict] = []
    uploaded_paths: list[str] = []

    for file in files:
        content_type = _resolve_content_type(file)
        if not content_type:
            await _cleanup_batch(uploaded_paths, group_slug, client)
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file.filename}",
            )

        content_bytes = await file.read()
        is_binary = content_type not in _TEXT_TYPES
        max_size = _MAX_SIZE_BINARY if is_binary else _MAX_SIZE_TEXT
        if len(content_bytes) > max_size:
            await _cleanup_batch(uploaded_paths, group_slug, client)
            raise HTTPException(
                status_code=400,
                detail=f"File {file.filename} too large. Max {max_size // (1024*1024)} MB.",
            )
        if len(content_bytes) == 0:
            await _cleanup_batch(uploaded_paths, group_slug, client)
            raise HTTPException(status_code=400, detail=f"File {file.filename} is empty.")

        slug = generate_slug()
        ext = _ALLOWED_TYPES[content_type]
        storage_path = f"shares/{slug}.{ext}"
        delete_token = generate_delete_token()

        # Upload to storage
        try:
            await asyncio.to_thread(
                lambda sp=storage_path, cb=content_bytes, ct=content_type: client.storage.from_("html-files").upload(
                    sp, cb, file_options={"content-type": ct, "upsert": "true"}
                ),
            )
        except Exception as exc:
            logger.error("Storage upload failed for slug=%s: %s", slug, exc)
            await _cleanup_batch(uploaded_paths, group_slug, client)
            raise HTTPException(status_code=500, detail=f"Failed to upload {file.filename}") from exc

        uploaded_paths.append(storage_path)

        # Extract text (only for text-based files)
        plain_text = None
        if content_type in _TEXT_TYPES:
            content_str = content_bytes.decode("utf-8", errors="replace")
            if content_type in ("text/html", "text/htm"):
                plain_text = extract_text_from_html(content_str)
            else:
                plain_text = extract_text_from_markdown(content_str)

        share_url = f"{settings.supabase_url}/storage/v1/object/public/html-files/{storage_path}"
        filename = file.filename or f"upload.{ext}"

        row_data: dict = {
            "slug": slug,
            "user_id": user.id if user else None,
            "storage_path": storage_path,
            "filename": filename,
            "title": None,
            "is_private": False,
            "delete_token": delete_token,
            "content_text": plain_text[:5000] if plain_text else None,
            "file_size": len(content_bytes),
            "mime_type": content_type,
            "source": "upload",
            "group_id": group_slug,
            "expires_at": expires_at,
        }
        if max_downloads is not None:
            row_data["max_downloads"] = max_downloads

        try:
            await asyncio.to_thread(
                lambda rd=row_data: client.table("shares").insert(rd).execute(),
            )
        except Exception as exc:
            logger.error("DB insert failed for slug=%s: %s", slug, exc)
            await _cleanup_batch(uploaded_paths, group_slug, client)
            raise HTTPException(status_code=500, detail=f"Failed to save {file.filename}") from exc

        uploaded_files.append({
            "slug": slug,
            "url": share_url,
            "filename": filename,
            "deleteToken": delete_token,
        })

    group_url = f"{settings.frontend_url}/g/{group_slug}"
    return {
        "group_slug": group_slug,
        "group_url": group_url,
        "files": uploaded_files,
    }


def _resolve_content_type(file: UploadFile) -> str | None:
    """Determine valid content type from UploadFile metadata."""
    # Check content_type first
    ct = (file.content_type or "").lower().split(";")[0].strip()
    if ct in _ALLOWED_TYPES:
        return ct

    # Fallback: check filename extension
    if file.filename:
        fname = file.filename.lower()
        for ext, mapped_ct in _EXT_MAP.items():
            if fname.endswith(ext):
                return mapped_ct

    return None


def _resolve_expiration(expires_in: str | None) -> int:
    """Resolve expiration string to seconds (A4). Accepts '1h','6h','24h','7d','30d' or int."""
    if expires_in is None:
        return _DEFAULT_EXPIRATION
    expires_in = expires_in.strip()
    if expires_in in _EXPIRATION_OPTIONS:
        return _EXPIRATION_OPTIONS[expires_in]
    try:
        val = int(expires_in)
        if val < 60:
            raise HTTPException(status_code=400, detail="Minimum expiration is 60 seconds")
        if val > _EXPIRATION_OPTIONS["30d"]:
            raise HTTPException(status_code=400, detail="Maximum expiration is 30 days")
        return val
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid expires_in. Use: {', '.join(_EXPIRATION_OPTIONS.keys())} or seconds as integer.",
        )


async def _cleanup_storage(storage_path: str) -> None:
    """Remove uploaded file from storage (compensating transaction)."""
    try:
        client = get_admin_client()
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").remove([storage_path]),
        )
    except Exception:
        logger.warning(
            "Failed to cleanup storage path=%s", storage_path, exc_info=True
        )


async def _cleanup_batch(uploaded_paths: list[str], group_slug: str, client) -> None:
    """Compensating transaction for batch upload failures (A1)."""
    if uploaded_paths:
        try:
            await asyncio.to_thread(
                lambda: client.storage.from_("html-files").remove(uploaded_paths),
            )
        except Exception:
            logger.warning("Failed to cleanup batch storage paths=%s", uploaded_paths, exc_info=True)
    try:
        await asyncio.to_thread(
            lambda: client.table("share_groups").delete().eq("slug", group_slug).execute(),
        )
    except Exception:
        logger.warning("Failed to cleanup share_group slug=%s", group_slug, exc_info=True)
