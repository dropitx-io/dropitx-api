"""CLI-friendly upload endpoint — curl/pipe compatible.

Provides a transfer.sh-like upload interface for developers.
Supports:
  - Multipart form upload: curl -F file=@file.txt https://api.dropitx.com/api/cli/upload
  - Raw body upload: echo hello | curl -X POST --data-binary @- https://api.dropitx.com/api/cli/upload
  - API key auth via Authorization header or X-API-Key header
  - Returns share URL in X-DropItX-URL response header
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Request, UploadFile, File, Form
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from app.dependencies import ApiKeyAuth, User, get_client_ip, get_optional_user
from core.config import settings
from core.extract_text import extract_text_from_html, extract_text_from_markdown
from core.nanoid import generate_delete_token, generate_slug
from core.rate_limit import check_upload_rate_limit, rate_limit_exceeded
from core.security import hash_api_key
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cli", tags=["CLI"])

# Reuse the same allowed types from internal upload
from app.internal.upload import (
    _ALLOWED_TYPES,
    _EXT_MAP,
    _TEXT_TYPES,
    _MAX_SIZE_TEXT,
    _MAX_SIZE_BINARY,
    _EXPIRATION_OPTIONS,
    _DEFAULT_EXPIRATION,
    _resolve_expiration,
    _resolve_content_type,
    _cleanup_storage,
)

# Slug map for CLI-friendly expiration names
_CLI_EXPIRATION_MAP: dict[str, str] = {
    "1h": "1h",
    "6h": "6h",
    "24h": "24h",
    "1d": "24h",
    "7d": "7d",
    "1w": "7d",
    "30d": "30d",
    "1m": "30d",
}


def _resolve_cli_expiration(expires: str | None) -> int:
    """Resolve CLI-friendly expiration string to seconds."""
    if expires is None:
        return _DEFAULT_EXPIRATION
    expires = expires.strip().lower()
    # Map CLI shorthand to server values
    mapped = _CLI_EXPIRATION_MAP.get(expires, expires)
    return _resolve_expiration(mapped)


async def _get_api_key_user(request: Request) -> ApiKeyAuth | None:
    """Extract API key auth from Authorization or X-API-Key header."""
    # Try Authorization: Bearer sk_xxx
    auth_header = request.headers.get("authorization", "")
    raw_key = None
    if auth_header.lower().startswith("bearer "):
        raw_key = auth_header[7:].strip()
    
    # Try X-API-Key header
    if not raw_key:
        raw_key = request.headers.get("x-api-key")
    
    if not raw_key:
        return None
    
    if not raw_key.startswith(("shk_", "sht_")):
        return None
    
    key_hash = hash_api_key(raw_key)
    
    try:
        client = get_admin_client()
        resp = await asyncio.to_thread(
            lambda: client.table("api_keys")
            .select("id, user_id, team_id, revoked_at")
            .eq("key_hash", key_hash)
            .execute(),
        )
        rows = resp.data or []
        if not rows:
            return None
        
        row = rows[0]
        if row.get("revoked_at") is not None:
            return None
        
        team_id = row.get("team_id")
        if team_id:
            membership = await asyncio.to_thread(
                lambda: client.table("team_members")
                .select("id")
                .eq("team_id", team_id)
                .eq("user_id", row["user_id"])
                .execute(),
            )
            if not membership.data:
                return None
        
        # Fire-and-forget last_used_at update
        asyncio.create_task(_update_last_used(row["id"]))
        
        return ApiKeyAuth(
            user_id=row["user_id"],
            key_id=row["id"],
            team_id=team_id,
        )
    except Exception as exc:
        logger.warning("CLI API key lookup failed: %s", exc)
        return None


async def _update_last_used(key_id: str) -> None:
    """Fire-and-forget update of api_keys.last_used_at."""
    try:
        client = get_admin_client()
        await asyncio.to_thread(
            lambda: client.table("api_keys")
            .update({"last_used_at": "now()"})
            .eq("id", key_id)
            .execute(),
        )
    except Exception:
        logger.warning("Failed to update last_used_at for key %s", key_id, exc_info=True)


def _resolve_content_type_from_bytes(data: bytes, filename: str | None) -> str | None:
    """Guess content type from filename extension."""
    if not filename:
        return "application/octet-stream"
    
    fname = filename.lower()
    for ext, mapped_ct in _EXT_MAP.items():
        if fname.endswith(ext):
            return mapped_ct
    
    return "application/octet-stream"


@router.post("/upload", tags=["CLI"])
async def cli_upload(
    request: Request,
    # Multipart form fields (optional — used when file is uploaded via form)
    file: UploadFile | None = File(default=None),
    # Query/form params
    password: str | None = Form(default=None),
    expires: str | None = Form(default=None),
    burn: bool = Form(default=False),
    slug: str | None = Form(default=None),
    # API key auth (optional)
    x_api_key: str | None = Header(default=None),
):
    """CLI-friendly upload endpoint.
    
    Supports:
    - Multipart form: curl -F file=@file.txt https://api.dropitx.com/api/cli/upload
    - Raw body: echo hello | curl -X POST --data-binary @- https://api.dropitx.com/api/cli/upload
    - Query params: ?password=secret&expires=1h&burn=true&slug=my-name
    
    Returns:
    - JSON response with share URL, slug, delete token
    - X-DropItX-URL header with the share URL
    - X-DropItX-Slug header with the slug
    - X-DropItX-Delete-Token header with delete token
    """
    # Rate limit
    ip = get_client_ip(request)
    rate = await asyncio.to_thread(check_upload_rate_limit, ip)
    if not rate.success:
        raise rate_limit_exceeded(rate)
    
    # Get API key auth (optional)
    api_key_auth = None
    if x_api_key:
        if x_api_key.startswith(("shk_", "sht_")):
            key_hash = hash_api_key(x_api_key)
            try:
                client = get_admin_client()
                resp = await asyncio.to_thread(
                    lambda: client.table("api_keys")
                    .select("id, user_id, team_id, revoked_at")
                    .eq("key_hash", key_hash)
                    .execute(),
                )
                rows = resp.data or []
                if rows and rows[0].get("revoked_at") is None:
                    row = rows[0]
                    api_key_auth = ApiKeyAuth(
                        user_id=row["user_id"],
                        key_id=row["id"],
                        team_id=row.get("team_id"),
                    )
            except Exception:
                pass
    
    # Also try Authorization header
    if not api_key_auth:
        api_key_auth = await _get_api_key_user(request)
    
    # Read content
    if file is not None:
        # Multipart form upload
        content_bytes = await file.read()
        filename = file.filename or "upload"
        content_type = _resolve_content_type(file) or _resolve_content_type_from_bytes(content_bytes, filename)
    else:
        # Raw body upload
        content_bytes = await request.body()
        if not content_bytes:
            raise HTTPException(status_code=400, detail="No file provided. Use multipart form or pipe content.")
        filename = None
        content_type = "application/octet-stream"
    
    if not content_type:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    
    # Validate size
    is_binary = content_type not in _TEXT_TYPES
    max_size = _MAX_SIZE_BINARY if is_binary else _MAX_SIZE_TEXT
    if len(content_bytes) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {max_size // (1024*1024)} MB.",
        )
    if len(content_bytes) == 0:
        raise HTTPException(status_code=400, detail="File is empty")
    
    # Validate slug (must be alphanumeric, 3-32 chars)
    if slug:
        import re
        if not re.match(r'^[a-zA-Z0-9_-]{3,32}$', slug):
            raise HTTPException(
                status_code=400,
                detail="Slug must be 3-32 characters, alphanumeric with hyphens/underscores",
            )
    
    # Resolve expiration
    expires_seconds = _resolve_cli_expiration(expires)
    
    # Generate identifiers
    if not slug:
        slug = generate_slug()
    ext = _ALLOWED_TYPES.get(content_type, "bin")
    storage_path = f"shares/{slug}.{ext}"
    delete_token = generate_delete_token()
    
    # Encrypt password if provided
    password_hash = None
    if password:
        from core.security import hash_password
        password_hash = hash_password(password)
    
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
        logger.error("CLI upload failed for slug=%s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to upload file") from exc
    
    # Extract text for search
    plain_text = ""
    if content_type in _TEXT_TYPES:
        content_str = content_bytes.decode("utf-8", errors="replace")
        if content_type in ("text/html", "text/htm"):
            plain_text = extract_text_from_html(content_str)
        else:
            plain_text = extract_text_from_markdown(content_str)
    
    # Calculate expires_at
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)).isoformat()
    
    # Build row data
    row_data: dict = {
        "slug": slug,
        "user_id": api_key_auth.user_id if api_key_auth else None,
        "storage_path": storage_path,
        "filename": filename or f"{slug}.{ext}",
        "title": None,
        "is_private": False,
        "delete_token": delete_token,
        "content_text": plain_text[:5000] if plain_text else None,
        "file_size": len(content_bytes),
        "mime_type": content_type,
        "source": "upload",  # readers pick the bucket from source; CLI files go to html-files
        "encrypted": False,
        "encryption_iv": None,
        "encryption_salt": None,
        "burn_after_reading": burn,
        "expires_at": expires_at,
        "password_hash": password_hash,
    }
    
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("shares").insert(row_data).execute(),
        )
        share_row = resp.data[0]
    except Exception as exc:
        logger.error("CLI DB insert failed for slug=%s: %s", slug, exc)
        await _cleanup_storage(storage_path)
        raise HTTPException(status_code=500, detail="Failed to save share") from exc
    
    # Build share URL
    share_url = f"{settings.frontend_url}/s/{slug}"
    
    # Build response
    result = {
        "slug": slug,
        "url": share_url,
        "filename": filename or f"{slug}.{ext}",
        "deleteToken": delete_token,
        "size": len(content_bytes),
        "expires_at": expires_at,
        "burn_after_reading": burn,
        "password_protected": bool(password),
    }
    
    response = JSONResponse(content=result)
    response.headers["X-DropItX-URL"] = share_url
    response.headers["X-DropItX-Slug"] = slug
    response.headers["X-DropItX-Delete-Token"] = delete_token
    
    return response


@router.post("/upload/text", tags=["CLI"])
async def cli_upload_text(
    request: Request,
    content: str = Form(...),
    filename: str | None = Form(default=None),
    password: str | None = Form(default=None),
    expires: str | None = Form(default=None),
    burn: bool = Form(default=False),
    slug: str | None = Form(default=None),
    x_api_key: str | None = Header(default=None),
):
    """Upload text content directly (for echo/pipe usage).
    
    curl -X POST https://api.dropitx.com/api/cli/upload/text \
      -F "content=hello world" \
      -F "expires=1h"
    """
    # Rate limit
    ip = get_client_ip(request)
    rate = await asyncio.to_thread(check_upload_rate_limit, ip)
    if not rate.success:
        raise rate_limit_exceeded(rate)
    
    # Get API key auth (optional)
    api_key_auth = None
    if x_api_key and x_api_key.startswith(("shk_", "sht_")):
        key_hash = hash_api_key(x_api_key)
        try:
            client = get_admin_client()
            resp = await asyncio.to_thread(
                lambda: client.table("api_keys")
                .select("id, user_id, team_id, revoked_at")
                .eq("key_hash", key_hash)
                .execute(),
            )
            rows = resp.data or []
            if rows and rows[0].get("revoked_at") is None:
                row = rows[0]
                api_key_auth = ApiKeyAuth(
                    user_id=row["user_id"],
                    key_id=row["id"],
                    team_id=row.get("team_id"),
                )
        except Exception:
            pass
    
    if not content:
        raise HTTPException(status_code=400, detail="Content is empty")
    
    content_bytes = content.encode("utf-8")
    
    # Validate size
    if len(content_bytes) > _MAX_SIZE_TEXT:
        raise HTTPException(
            status_code=400,
            detail=f"Content too large. Maximum size is {_MAX_SIZE_TEXT // (1024*1024)} MB.",
        )
    
    # Validate slug
    if slug:
        import re
        if not re.match(r'^[a-zA-Z0-9_-]{3,32}$', slug):
            raise HTTPException(
                status_code=400,
                detail="Slug must be 3-32 characters, alphanumeric with hyphens/underscores",
            )
    
    # Resolve expiration
    expires_seconds = _resolve_cli_expiration(expires)
    
    # Generate identifiers
    if not slug:
        slug = generate_slug()
    ext = "txt"
    storage_path = f"shares/{slug}.{ext}"
    delete_token = generate_delete_token()
    
    # Encrypt password if provided
    password_hash = None
    if password:
        from core.security import hash_password
        password_hash = hash_password(password)
    
    # Upload to Supabase Storage
    client = get_admin_client()
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").upload(
                storage_path,
                content_bytes,
                file_options={"content-type": "text/plain", "upsert": "true"},
            ),
        )
    except Exception as exc:
        logger.error("CLI text upload failed for slug=%s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to upload content") from exc
    
    # Extract text for search
    plain_text = extract_text_from_markdown(content)
    
    # Calculate expires_at
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)).isoformat()
    
    # Build row data
    row_data: dict = {
        "slug": slug,
        "user_id": api_key_auth.user_id if api_key_auth else None,
        "storage_path": storage_path,
        "filename": filename or f"{slug}.txt",
        "title": None,
        "is_private": False,
        "delete_token": delete_token,
        "content_text": plain_text[:5000] if plain_text else None,
        "file_size": len(content_bytes),
        "mime_type": "text/plain",
        "source": "upload",  # readers pick the bucket from source; CLI files go to html-files
        "encrypted": False,
        "encryption_iv": None,
        "encryption_salt": None,
        "burn_after_reading": burn,
        "expires_at": expires_at,
        "password_hash": password_hash,
    }
    
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("shares").insert(row_data).execute(),
        )
        share_row = resp.data[0]
    except Exception as exc:
        logger.error("CLI text DB insert failed for slug=%s: %s", slug, exc)
        await _cleanup_storage(storage_path)
        raise HTTPException(status_code=500, detail="Failed to save share") from exc
    
    # Build share URL
    share_url = f"{settings.frontend_url}/s/{slug}"
    
    # Build response
    result = {
        "slug": slug,
        "url": share_url,
        "filename": filename or f"{slug}.txt",
        "deleteToken": delete_token,
        "size": len(content_bytes),
        "expires_at": expires_at,
        "burn_after_reading": burn,
        "password_protected": bool(password),
    }
    
    response = JSONResponse(content=result)
    response.headers["X-DropItX-URL"] = share_url
    response.headers["X-DropItX-Slug"] = slug
    response.headers["X-DropItX-Delete-Token"] = delete_token
    
    return response
