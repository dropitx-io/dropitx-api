"""Languages endpoint — list supported programming languages for syntax highlighting."""

from __future__ import annotations

from fastapi import APIRouter

from core.language_detect import get_all_languages

router = APIRouter()


@router.get("/languages", tags=["Languages"], summary="List supported languages")
async def list_languages():
    """Get all supported programming languages for syntax highlighting.

    Returns language IDs, names, and file extensions.
    Use these IDs in the `language` parameter when uploading code files.
    """
    return {
        "languages": get_all_languages(),
        "total": len(get_all_languages()),
    }
