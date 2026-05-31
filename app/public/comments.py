"""Comments/feedback endpoints (A7)."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.dependencies import User, get_client_ip, get_optional_user
from core.rate_limit import check_upload_rate_limit
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


class CommentCreate(BaseModel):
    """Request to add a comment."""
    author_name: str = Field(default="Anonymous", max_length=100)
    content: str = Field(..., min_length=1, max_length=5000)
    parent_id: str | None = None


class CommentResponse(BaseModel):
    """A single comment."""
    id: str
    share_slug: str
    author_name: str
    content: str
    created_at: str
    user_id: str | None = None
    parent_id: str | None = None


class CommentListResponse(BaseModel):
    """Paginated comment list."""
    comments: list[CommentResponse]
    total: int
    page: int
    per_page: int


@router.get("/{slug}/comments", response_model=CommentListResponse, tags=["Comments"])
async def list_comments(
    slug: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    """List comments for a share (paginated)."""
    client = get_admin_client()

    # Verify share exists
    try:
        share_resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("slug")
            .eq("slug", slug)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to verify slug for comments: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load comments") from exc

    if not share_resp.data:
        raise HTTPException(status_code=404, detail="Share not found")

    offset = (page - 1) * per_page

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("share_comments")
            .select("*", count="exact")
            .eq("share_slug", slug)
            .order("created_at", desc=True)
            .range(offset, offset + per_page - 1)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to fetch comments: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load comments") from exc

    rows = resp.data or []
    total = resp.count or 0

    comments = [
        CommentResponse(
            id=r["id"],
            share_slug=r["share_slug"],
            author_name=r["author_name"],
            content=r["content"],
            created_at=r["created_at"],
            user_id=r.get("user_id"),
            parent_id=r.get("parent_id"),
        )
        for r in rows
    ]

    return CommentListResponse(
        comments=comments,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/{slug}/comments", response_model=CommentResponse, tags=["Comments"])
async def add_comment(
    slug: str,
    body: CommentCreate,
    request: Request,
    user: User | None = Depends(get_optional_user),
):
    """Add a comment to a share. Rate limited."""
    # Rate limit
    ip = get_client_ip(request)
    rate = await asyncio.to_thread(check_upload_rate_limit, ip)
    if not rate.success:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    client = get_admin_client()

    # Verify share exists
    try:
        share_resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("slug")
            .eq("slug", slug)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to verify slug for comment: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to add comment") from exc

    if not share_resp.data:
        raise HTTPException(status_code=404, detail="Share not found")

    # Insert comment
    comment_data = {
        "share_slug": slug,
        "user_id": user.id if user else None,
        "author_name": body.author_name,
        "content": body.content,
        "parent_id": body.parent_id,
    }

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("share_comments")
            .insert(comment_data)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to insert comment: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to add comment") from exc

    row = resp.data[0] if resp.data else {}

    return CommentResponse(
        id=row.get("id", ""),
        share_slug=slug,
        author_name=body.author_name,
        content=body.content,
        created_at=row.get("created_at", ""),
        user_id=user.id if user else None,
        parent_id=body.parent_id,
    )
