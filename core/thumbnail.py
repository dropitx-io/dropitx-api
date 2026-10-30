"""Thumbnail generation for uploaded images.

Generates a small thumbnail (max 200x200) and stores it in object storage
at `public/thumbnails/{storage_base}_thumb.jpg` under the `html-files` bucket.
"""

from __future__ import annotations

import asyncio
import io
import logging

from core.db import PUBLIC_PREFIX, public_object_url
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

# Supported image MIME types for thumbnail generation
_THUMB_IMAGE_TYPES: set[str] = {
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "image/bmp", "image/tiff",
}

_THUMB_MAX_SIZE = (200, 200)  # max width, height in pixels
_THUMB_QUALITY = 80  # JPEG quality


def thumbnail_key(storage_path: str) -> str:
    """Key of the public thumbnail for an object.

    shares/abc123.png -> public/thumbnails/shares/abc123_thumb.jpg
    """
    base = storage_path.rsplit(".", 1)[0] if "." in storage_path else storage_path
    return f"{PUBLIC_PREFIX}thumbnails/{base}_thumb.jpg"


async def maybe_generate_thumbnail(
    content_bytes: bytes,
    mime_type: str,
    storage_path: str,
) -> str | None:
    """Generate a thumbnail for image uploads.

    Args:
        content_bytes: The raw image bytes.
        mime_type: The MIME type of the image.
        storage_path: The storage path of the original file (e.g., "shares/abc123.png").

    Returns:
        The public URL of the thumbnail, or None if generation failed or not applicable.
    """
    if mime_type not in _THUMB_IMAGE_TYPES:
        return None

    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed — skipping thumbnail generation")
        return None

    try:
        # Run image processing in thread pool (Pillow is synchronous)
        thumb_bytes = await asyncio.to_thread(
            _generate_thumb_bytes, content_bytes
        )
        if thumb_bytes is None:
            return None

        thumb_path = thumbnail_key(storage_path)

        # Upload thumbnail to storage
        client = get_admin_client()
        await asyncio.to_thread(
            lambda: client.storage.from_("html-files").upload(
                thumb_path,
                thumb_bytes,
                file_options={"content-type": "image/jpeg", "upsert": "true"},
            ),
        )

        logger.info("Thumbnail generated: %s", thumb_path)
        return public_object_url("html-files", thumb_path)

    except Exception as exc:
        logger.warning("Thumbnail generation failed for %s: %s", storage_path, exc)
        return None


def _generate_thumb_bytes(content_bytes: bytes) -> bytes | None:
    """Generate thumbnail bytes from image bytes (synchronous).

    Returns JPEG bytes or None on failure.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(content_bytes))

        # Convert to RGB (handles RGBA, palette, etc.)
        if img.mode in ("RGBA", "LA", "P"):
            # Create white background for transparency
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize maintaining aspect ratio
        img.thumbnail(_THUMB_MAX_SIZE, Image.LANCZOS)

        # Encode as JPEG
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_THUMB_QUALITY, optimize=True)
        return buf.getvalue()

    except Exception as exc:
        logger.warning("Pillow thumbnail error: %s", exc)
        return None


async def maybe_generate_thumbnail_for_batch(
    content_bytes: bytes,
    mime_type: str,
    storage_path: str,
) -> str | None:
    """Same as maybe_generate_thumbnail but for batch upload context."""
    return await maybe_generate_thumbnail(content_bytes, mime_type, storage_path)
