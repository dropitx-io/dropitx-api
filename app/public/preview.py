"""File preview endpoint — preview files before downloading.

Supports: images, PDF, code (syntax), markdown (rendered),
video/audio (inline player), and text (first N lines).
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.public.shares import _check_download_limit, _fetch_share
from app.dependencies import User, get_client_ip, get_optional_user
from core.db import public_object_url
from core.rate_limit import check_public_read_rate_limit
from core.share_urls import share_page_url
from core.supabase import get_admin_client
from core.thumbnail import thumbnail_key

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Code language detection from extension
# ---------------------------------------------------------------------------

_CODE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".lua": "lua",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".fish": "fish",
    ".ps1": "powershell",
    ".sql": "sql",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".vue": "vue",
    ".svelte": "svelte",
    ".dart": "dart",
    ".zig": "zig",
    ".nim": "nim",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".clj": "clojure",
    ".lisp": "lisp",
    ".el": "lisp",
    ".vim": "vim",
    ".dockerfile": "dockerfile",
    ".makefile": "makefile",
    ".cmake": "cmake",
    ".gradle": "gradle",
    ".ini": "ini",
    ".cfg": "ini",
    ".env": "bash",
    ".diff": "diff",
    ".patch": "diff",
    ".graphql": "graphql",
    ".proto": "protobuf",
    ".tf": "hcl",
    ".hcl": "hcl",
    ".mdx": "mdx",
}


def _detect_code_language(filename: str) -> str:
    """Detect programming language from file extension."""
    if not filename:
        return "plaintext"
    # Handle special filenames
    lower = filename.lower()
    if lower in ("makefile", "dockerfile", "vagrantfile", "gemfile", "rakefile"):
        return lower
    # Get extension
    dot_idx = lower.rfind(".")
    if dot_idx == -1:
        return "plaintext"
    ext = lower[dot_idx:]
    return _CODE_EXTENSIONS.get(ext, "plaintext")


# ---------------------------------------------------------------------------
# Preview type classification
# ---------------------------------------------------------------------------

_PREVIEW_IMAGE_TYPES: set[str] = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "image/bmp", "image/svg+xml", "image/tiff",
}

_PREVIEW_CODE_MIME_PREFIXES: set[str] = {
    "text/x-",  # text/x-python, text/x-java, etc.
    "application/x-",
    "application/javascript",
    "application/typescript",
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/sql",
    "application/x-sh",
}

_PREVIEW_TEXT_TYPES: set[str] = {
    "text/plain",
    "text/csv",
    "text/tab-separated-values",
}

_MARKDOWN_TYPES: set[str] = {
    "text/markdown",
    "text/x-markdown",
    "application/markdown",
}

_PDF_TYPES: set[str] = {
    "application/pdf",
}

_VIDEO_TYPES: set[str] = {
    "video/mp4", "video/webm", "video/quicktime",
    "video/x-msvideo", "video/x-matroska", "video/ogg",
}

_AUDIO_TYPES: set[str] = {
    "audio/mpeg", "audio/ogg", "audio/wav", "audio/flac",
    "audio/aac", "audio/webm", "audio/mp4", "audio/x-m4a",
}

# Max characters to return for text content previews
_MAX_TEXT_PREVIEW = 50_000  # ~50KB of text


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

PreviewType = Literal[
    "image", "pdf", "code", "markdown", "video", "audio", "text", "unsupported"
]


class PreviewResponse(BaseModel):
    """Preview data for a share."""
    slug: str
    filename: str | None = None
    title: str | None = None
    mime_type: str
    file_size: int | None = None
    preview_type: PreviewType
    content_url: str  # Share page URL (empty when the share is password-protected)
    content: str | None = None  # For text/code/markdown: preview content
    language: str | None = None  # For code: detected language
    lines_total: int | None = None  # For text: total line count
    lines_shown: int | None = None  # For text: lines actually returned
    thumbnail_url: str | None = None  # For images: thumbnail URL if available
    encrypted: bool = False
    password_protected: bool = False
    burn_after_reading: bool = False
    burned: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_preview(mime_type: str, filename: str) -> tuple[PreviewType, str | None]:
    """Classify a file into a preview type and optional language.

    Returns (preview_type, language | None).
    """
    mime_lower = mime_type.lower().strip()
    fname_lower = filename.lower() if filename else ""

    # Images
    if mime_lower in _PREVIEW_IMAGE_TYPES or mime_lower.startswith("image/"):
        return ("image", None)

    # PDF
    if mime_lower in _PDF_TYPES:
        return ("pdf", None)

    # Video
    if mime_lower in _VIDEO_TYPES or mime_lower.startswith("video/"):
        return ("video", None)

    # Audio
    if mime_lower in _AUDIO_TYPES or mime_lower.startswith("audio/"):
        return ("audio", None)

    # Markdown
    if mime_lower in _MARKDOWN_TYPES or fname_lower.endswith((".md", ".mdx", ".markdown")):
        return ("markdown", None)

    # Code — check mime prefix or extension
    if any(mime_lower.startswith(prefix) for prefix in _PREVIEW_CODE_MIME_PREFIXES):
        lang = _detect_code_language(fname_lower)
        return ("code", lang)

    # Plain text
    if mime_lower in _PREVIEW_TEXT_TYPES or mime_lower.startswith("text/"):
        # Check if it might be code based on extension
        lang = _detect_code_language(fname_lower)
        if lang != "plaintext":
            return ("code", lang)
        return ("text", None)

    # Fallback: try extension-based detection
    lang = _detect_code_language(fname_lower)
    if lang != "plaintext":
        return ("code", lang)

    return ("unsupported", None)


def _build_thumbnail_url(storage_path: str) -> str | None:
    """Build public URL for a thumbnail if it exists."""
    if "." not in storage_path:
        return None
    return public_object_url("html-files", thumbnail_key(storage_path))


# ---------------------------------------------------------------------------
# GET /shares/{slug}/preview — get preview data for a share
# ---------------------------------------------------------------------------

@router.get(
    "/shares/{slug}/preview",
    tags=["Shares"],
    summary="Preview a share before downloading",
    response_model=PreviewResponse,
)
async def get_share_preview(
    slug: str,
    request: Request,
    max_lines: int = Query(default=100, ge=10, le=1000, description="Max lines for text previews"),
    user: User | None = Depends(get_optional_user),
):
    """Get preview data for a share without triggering a download.

    Returns structured preview info (content_url is the share page URL, never a storage URL):
    - **image**: thumbnail_url if available
    - **pdf**: client-side viewer
    - **code**: content contains syntax-highlightable source; language detected
    - **markdown**: content contains raw markdown for client-side rendering
    - **video/audio**: inline player
    - **text**: content contains first N lines of the file
    - **unsupported**: file type cannot be previewed

    Does NOT increment download count. Does NOT trigger burn-after-reading.
    """
    ip = get_client_ip(request)
    rate = check_public_read_rate_limit(ip)
    if not rate.success:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(rate.reset, 1))},
        )

    row = await _fetch_share(slug, viewer=user, enforce_private=True)

    # Check download limit (but don't increment)
    _check_download_limit(row)

    # Password-protected shares return limited info
    if row.get("password_hash"):
        return PreviewResponse(
            slug=row["slug"],
            filename=row.get("filename"),
            title=row.get("title"),
            mime_type=row.get("mime_type", "application/octet-stream"),
            file_size=row.get("file_size"),
            preview_type="unsupported",
            content_url="",
            password_protected=True,
            encrypted=row.get("encrypted", False),
            burn_after_reading=row.get("burn_after_reading", False),
            burned=row.get("burned", False),
        )

    # Determine storage paths
    storage_path = row["storage_path"]
    source = row.get("source", "")
    bucket = "html-files" if source in ("upload", "editor") else "shares"

    # Classify the file
    mime_type = row.get("mime_type", "application/octet-stream")
    filename = row.get("filename", "")
    preview_type, language = _classify_preview(mime_type, filename)

    # Build URLs
    content_url = share_page_url(row["slug"])
    thumbnail_url = _build_thumbnail_url(storage_path)

    # For text-based previews, fetch and return content
    content = None
    lines_total = None
    lines_shown = None

    if preview_type in ("code", "markdown", "text"):
        try:
            client = get_admin_client()
            resp = await asyncio.to_thread(
                lambda: client.storage.from_(bucket).download(storage_path),
            )
            raw = resp.decode("utf-8", errors="replace") if isinstance(resp, bytes) else str(resp)

            # Count total lines
            all_lines = raw.split("\n")
            lines_total = len(all_lines)

            if preview_type == "markdown":
                # Return full markdown for client rendering (up to limit)
                content = raw[:_MAX_TEXT_PREVIEW]
            else:
                # Return first N lines for text/code
                preview_lines = all_lines[:max_lines]
                content = "\n".join(preview_lines)
                lines_shown = len(preview_lines)

                # Truncate if still too large
                if len(content) > _MAX_TEXT_PREVIEW:
                    content = content[:_MAX_TEXT_PREVIEW]

        except Exception as exc:
            logger.warning("Failed to fetch text content for preview %s: %s", slug, exc)
            # Don't fail — just return without content
            content = None

    return PreviewResponse(
        slug=row["slug"],
        filename=filename,
        title=row.get("title"),
        mime_type=mime_type,
        file_size=row.get("file_size"),
        preview_type=preview_type,
        content_url=content_url,
        content=content,
        language=language,
        lines_total=lines_total,
        lines_shown=lines_shown,
        thumbnail_url=thumbnail_url,
        encrypted=row.get("encrypted", False),
        password_protected=False,
        burn_after_reading=row.get("burn_after_reading", False),
        burned=row.get("burned", False),
    )
