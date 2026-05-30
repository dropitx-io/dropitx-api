"""Comments/Discussion endpoints — CRUD for share comments with nested replies."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.dependencies import User, get_optional_user
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CommentCreate(BaseModel):
    """Create a new comment (or reply)."""
    content: str = Field(..., min_length=1, max_length=5000)
    parent_id: str | None = Field(default=None, description="UUID of parent comment for nested replies")
    nickname: str | None = Field(default=None, max_length=50, description="Display name for anonymous users")


class CommentUpdate(BaseModel):
    """Update an existing comment's content."""
    content: str = Field(..., min_length=1, max_length=5000)


class CommentResponse(BaseModel):
    """A single comment returned to the client."""
    id: str
    share_id: str
    parent_id: str | None
    user_id: str | None
    nickname: str | None
    content: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class CommentThread(CommentResponse):
    """A comment with its nested replies."""
    replies: list[CommentThread] = []


class CommentListResponse(BaseModel):
    """Paginated list of top-level comments with nested replies."""
    comments: list[CommentThread]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _verify_share_exists(share_id: str) -> None:
    """Verify a share exists, raise 404 if not."""
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("shares")
        .select("id")
        .eq("id", share_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Share not found")


async def _verify_comment_exists(comment_id: str, share_id: str) -> dict:
    """Verify a comment exists and belongs to the share. Returns comment row."""
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("share_comments")
        .select("*")
        .eq("id", comment_id)
        .eq("share_id", share_id)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Comment not found")
    return rows[0]


def _authorize_comment_owner(comment: dict, user: User | None) -> None:
    """Verify the caller owns the comment. Raises 403 if not."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if comment.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this comment")


def _build_comment_tree(comments: list[dict]) -> list[CommentThread]:
    """Build a nested comment tree from a flat list."""
    by_id: dict[str, CommentThread] = {}
    roots: list[CommentThread] = []

    # First pass: create all nodes
    for c in comments:
        thread = CommentThread(**c, replies=[])
        by_id[c["id"]] = thread

    # Second pass: wire parent-child
    for c in comments:
        node = by_id[c["id"]]
        parent_id = c.get("parent_id")
        if parent_id and parent_id in by_id:
            by_id[parent_id].replies.append(node)
        elif not parent_id:
            roots.append(node)

    return roots


# ---------------------------------------------------------------------------
# GET /shares/{share_id}/comments
# ---------------------------------------------------------------------------

@router.get(
    "/shares/{share_id}/comments",
    response_model=CommentListResponse,
    tags=["Comments"],
)
async def list_comments(
    share_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: Literal["newest", "oldest"] = Query("oldest"),
):
    """List comments for a share with nested replies. Paginated."""
    await _verify_share_exists(share_id)

    client = get_admin_client()

    # Fetch all comments for this share (we build tree in Python)
    query = (
        client.table("share_comments")
        .select("*")
        .eq("share_id", share_id)
        .eq("is_deleted", False)
    )

    if sort == "newest":
        query = query.order("created_at", desc=True)
    else:
        query = query.order("created_at", desc=False)

    resp = await asyncio.to_thread(lambda: query.execute())
    all_comments = resp.data or []

    # Build tree
    tree = _build_comment_tree(all_comments)

    # Paginate top-level comments
    total = len(tree)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = tree[start:end]

    return CommentListResponse(
        comments=paginated,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# POST /shares/{share_id}/comments
# ---------------------------------------------------------------------------

@router.post(
    "/shares/{share_id}/comments",
    response_model=CommentResponse,
    status_code=201,
    tags=["Comments"],
)
async def create_comment(
    share_id: str,
    body: CommentCreate,
    user: User | None = Depends(get_optional_user),
):
    """Create a comment on a share. Anonymous with nickname or authenticated."""
    await _verify_share_exists(share_id)

    # If replying, verify parent exists
    if body.parent_id:
        await _verify_comment_exists(body.parent_id, share_id)

    client = get_admin_client()

    comment_data = {
        "share_id": share_id,
        "parent_id": body.parent_id,
        "user_id": user.id if user else None,
        "nickname": body.nickname if not user else None,
        "content": body.content,
    }

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("share_comments")
            .insert(comment_data)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to create comment for share=%s: %s", share_id, exc)
        raise HTTPException(status_code=500, detail="Failed to create comment") from exc

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to create comment")

    return CommentResponse(**rows[0])


# ---------------------------------------------------------------------------
# PATCH /shares/{share_id}/comments/{comment_id}
# ---------------------------------------------------------------------------

@router.patch(
    "/shares/{share_id}/comments/{comment_id}",
    response_model=CommentResponse,
    tags=["Comments"],
)
async def update_comment(
    share_id: str,
    comment_id: str,
    body: CommentUpdate,
    user: User | None = Depends(get_optional_user),
):
    """Update a comment's content. Must be the comment author."""
    comment = await _verify_comment_exists(comment_id, share_id)
    _authorize_comment_owner(comment, user)

    client = get_admin_client()

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("share_comments")
            .update({"content": body.content})
            .eq("id", comment_id)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to update comment=%s: %s", comment_id, exc)
        raise HTTPException(status_code=500, detail="Failed to update comment") from exc

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to update comment")

    return CommentResponse(**rows[0])


# ---------------------------------------------------------------------------
# DELETE /shares/{share_id}/comments/{comment_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/shares/{share_id}/comments/{comment_id}",
    tags=["Comments"],
)
async def delete_comment(
    share_id: str,
    comment_id: str,
    user: User | None = Depends(get_optional_user),
):
    """Soft-delete a comment. Must be the comment author."""
    comment = await _verify_comment_exists(comment_id, share_id)
    _authorize_comment_owner(comment, user)

    client = get_admin_client()

    try:
        await asyncio.to_thread(
            lambda: client.table("share_comments")
            .update({"is_deleted": True, "content": "[deleted]"})
            .eq("id", comment_id)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to delete comment=%s: %s", comment_id, exc)
        raise HTTPException(status_code=500, detail="Failed to delete comment") from exc

    return {"detail": "Comment deleted"}
