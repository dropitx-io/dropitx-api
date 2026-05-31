"""Document CRUD endpoints — authenticated via API key."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.dependencies import ApiKeyAuth, get_api_key
from app.v1.document_helpers import (
    extract_plain_text,
    fetch_content,
    find_document,
    infer_mime,
)
from core.nanoid import generate_delete_token, generate_slug
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["Documents"])

_STORAGE_BUCKET = "shares"

# ---------------------------------------------------------------------------
# Request / Response DTOs
# ---------------------------------------------------------------------------


class DocumentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5_000_000)
    filename: str | None = None
    title: str | None = None
    is_private: bool = False
    # E2E encryption
    encrypted: bool = False
    encryption_iv: str | None = None
    encryption_salt: str | None = None
    # Burn after reading
    burn_after_reading: bool = False
    # One-time download (file.io style)
    one_time_download: bool = False
    # Expiration
    expires_in: int | None = Field(default=None, description="Seconds until expiry")


class DocumentUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=5_000_000)
    filename: str | None = None
    title: str | None = None
    is_private: bool | None = None
    # E2E encryption (when updating encrypted content)
    encryption_iv: str | None = None
    encryption_salt: str | None = None


class DocumentResponse(BaseModel):
    id: str
    slug: str
    filename: str | None = None
    title: str | None = None
    content: str
    is_private: bool = False
    view_count: int = 0
    created_at: datetime
    updated_at: datetime
    # E2E encryption
    encrypted: bool = False
    encryption_iv: str | None = None
    encryption_salt: str | None = None
    # Burn after reading
    burn_after_reading: bool = False
    # One-time download
    one_time_download: bool = False
    # Expiration
    expires_at: datetime | None = None


def _to_response(row: dict, content: str) -> DocumentResponse:
    """Map a DB row + content bytes into a DocumentResponse."""
    return DocumentResponse(
        id=row["id"],
        slug=row["slug"],
        filename=row.get("filename"),
        title=row.get("title"),
        content=content,
        is_private=row.get("is_private", False),
        view_count=row.get("view_count", 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        encrypted=row.get("encrypted", False),
        encryption_iv=row.get("encryption_iv"),
        encryption_salt=row.get("encryption_salt"),
        burn_after_reading=row.get("burn_after_reading", False),
        one_time_download=row.get("one_time_download", False),
        expires_at=row.get("expires_at"),
    )


# ---------------------------------------------------------------------------
# Expiration helper
# ---------------------------------------------------------------------------

def _compute_expires_at(expires_in: int | None) -> str | None:
    """Convert expires_in (seconds) to an ISO timestamp string."""
    if expires_in is None:
        return None
    from datetime import timedelta
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return expires_at.isoformat()


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=DocumentResponse, status_code=201, summary="Create document")
async def create_document(
    body: DocumentCreate,
    auth: ApiKeyAuth = Depends(get_api_key),
) -> DocumentResponse:
    """Create a new document owned by the API key holder."""
    slug = generate_slug()
    delete_token = generate_delete_token()
    storage_path = f"{auth.user_id}/{slug}"
    content_text = extract_plain_text(body.content, body.filename)

    client = get_admin_client()

    try:
        await asyncio.to_thread(
            lambda: client.storage.from_(_STORAGE_BUCKET).upload(
                path=storage_path,
                file=body.content.encode("utf-8"),
                file_options={"content-type": infer_mime(body.filename)},
            ),
        )
    except Exception as exc:
        logger.error("Storage upload failed for %s: %s", storage_path, exc)
        raise HTTPException(status_code=500, detail="Failed to upload document") from exc

    row_data = {
        "slug": slug,
        "filename": body.filename or f"{slug}.txt",
        "storage_path": storage_path,
        "content_text": content_text,
        "file_size": len(body.content.encode("utf-8")),
        "mime_type": infer_mime(body.filename),
        "delete_token": delete_token,
        "user_id": auth.user_id,
        "title": body.title,
        "is_private": body.is_private,
        "source": "api",
        "encrypted": body.encrypted,
        "encryption_iv": body.encryption_iv,
        "encryption_salt": body.encryption_salt,
        "burn_after_reading": body.burn_after_reading,
        "one_time_download": body.one_time_download,
    }

    expires_at = _compute_expires_at(body.expires_in)
    if expires_at:
        row_data["expires_at"] = expires_at

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("shares").insert(row_data).execute(),
        )
        share_row = resp.data[0]
    except Exception as exc:
        logger.error("Share insert failed: %s", exc)
        try:
            await asyncio.to_thread(
                lambda: client.storage.from_(_STORAGE_BUCKET).remove([storage_path]),
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to create document") from exc

    if auth.team_id:
        try:
            await asyncio.to_thread(
                lambda: client.table("team_shares").insert({
                    "team_id": auth.team_id,
                    "share_id": share_row["id"],
                    "shared_by": auth.user_id,
                }).execute(),
            )
        except Exception as exc:
            logger.warning("team_shares insert failed for %s: %s", slug, exc)

    return _to_response(share_row, body.content)


@router.get("", response_model=list[DocumentResponse], summary="List documents")
async def list_documents(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    auth: ApiKeyAuth = Depends(get_api_key),
) -> list[DocumentResponse]:
    """List documents for the authenticated user or team."""
    client = get_admin_client()
    offset = (page - 1) * limit

    try:
        if auth.team_id:
            resp = await asyncio.to_thread(
                lambda: client.table("team_shares")
                .select("shares(*)")
                .eq("team_id", auth.team_id)
                .order("created_at", foreign_table="shares", desc=True)
                .range(offset, offset + limit - 1)
                .execute(),
            )
            rows = [item["shares"] for item in resp.data if item.get("shares")]
        else:
            resp = await asyncio.to_thread(
                lambda: client.table("shares")
                .select("*")
                .eq("user_id", auth.user_id)
                .order("created_at", desc=True)
                .range(offset, offset + limit - 1)
                .execute(),
            )
            rows = resp.data or []
    except Exception as exc:
        logger.error("Document list query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list documents") from exc

    results = []
    for row in rows:
        content = await fetch_content(client, row["storage_path"])
        results.append(_to_response(row, content))
    return results


@router.get("/{slug}", response_model=DocumentResponse, summary="Get document by slug")
async def get_document(
    slug: str,
    auth: ApiKeyAuth = Depends(get_api_key),
) -> DocumentResponse:
    """Get a single document by slug."""
    client = get_admin_client()
    row = await find_document(client, slug, auth)

    # Check expiration
    if row.get("expires_at"):
        from datetime import datetime as dt
        expires = row["expires_at"]
        if isinstance(expires, str):
            expires = dt.fromisoformat(expires.replace("Z", "+00:00"))
        if dt.now(timezone.utc) > expires:
            raise HTTPException(status_code=410, detail="Document has expired")

    content = await fetch_content(client, row["storage_path"])
    return _to_response(row, content)


@router.patch("/{slug}", response_model=DocumentResponse, summary="Update document")
async def update_document(
    slug: str,
    body: DocumentUpdate,
    auth: ApiKeyAuth = Depends(get_api_key),
) -> DocumentResponse:
    """Update an existing document. Saves a revision before updating."""
    if not body.content and body.filename is None and body.title is None and body.is_private is None:
        raise HTTPException(status_code=400, detail="No fields to update")

    client = get_admin_client()
    row = await find_document(client, slug, auth)

    # Save current state as a revision before updating
    if body.content:
        from app.v1.revisions import save_revision
        current_content = await fetch_content(client, row["storage_path"])
        await save_revision(
            row["id"],
            current_content,
            filename=row.get("filename"),
            title=row.get("title"),
        )

    update_data: dict = {}
    if body.content:
        update_data["content_text"] = extract_plain_text(
            body.content, body.filename or row.get("filename"),
        )
        update_data["file_size"] = len(body.content.encode("utf-8"))
    if body.filename is not None:
        update_data["filename"] = body.filename
    if body.title is not None:
        update_data["title"] = body.title
    if body.is_private is not None:
        update_data["is_private"] = body.is_private
    if body.encryption_iv is not None:
        update_data["encryption_iv"] = body.encryption_iv
    if body.encryption_salt is not None:
        update_data["encryption_salt"] = body.encryption_salt

    try:
        if body.content:
            await asyncio.to_thread(
                lambda: client.storage.from_(_STORAGE_BUCKET).update(
                    path=row["storage_path"],
                    file=body.content.encode("utf-8"),
                    file_options={"content-type": infer_mime(
                        update_data.get("filename", row.get("filename")),
                    )},
                ),
            )

        resp = await asyncio.to_thread(
            lambda: client.table("shares").update(update_data).eq("id", row["id"]).execute(),
        )
        updated = resp.data[0]
    except Exception as exc:
        logger.error("Document update failed for %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to update document") from exc

    final_content = body.content if body.content else await fetch_content(client, row["storage_path"])
    return _to_response(updated, final_content)


@router.delete("/{slug}", status_code=204, summary="Delete document")
async def delete_document(
    slug: str,
    auth: ApiKeyAuth = Depends(get_api_key),
) -> None:
    """Delete a document and its storage object."""
    client = get_admin_client()
    row = await find_document(client, slug, auth)

    try:
        await asyncio.to_thread(
            lambda: client.storage.from_(_STORAGE_BUCKET).remove([row["storage_path"]]),
        )
    except Exception as exc:
        logger.warning("Storage removal failed for %s: %s", row["storage_path"], exc)

    try:
        await asyncio.to_thread(
            lambda: client.table("shares").delete().eq("id", row["id"]).execute(),
        )
    except Exception as exc:
        logger.error("Share delete failed for %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to delete document") from exc
