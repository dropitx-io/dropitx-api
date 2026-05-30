"""Public full-text search via Supabase RPC."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from core.supabase import get_admin_client
from models.share import SearchResult

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /search
# ---------------------------------------------------------------------------

@router.get("/search", tags=["Search"])
async def search_shares(
    q: str = Query(min_length=2, max_length=200, description="Search query"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Results per page"),
):
    """Full-text search across public shares using Supabase RPC."""
    offset = (page - 1) * limit

    client = get_admin_client()
    try:
        resp = await asyncio.to_thread(
            lambda: client.rpc(
                "search_shares",
                {
                    "query_term": q,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            ).execute()
        )
    except Exception as exc:
        logger.error("Search RPC failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Search failed") from exc

    rows = resp.data or []

    results = [SearchResult(**row) for row in rows]

    response = JSONResponse(content={
        "results": [r.model_dump() for r in results],
        "page": page,
        "limit": limit,
        "total": len(results),
    })
    response.headers["cache-control"] = "public, max-age=30, stale-while-revalidate=60"
    return response
