"""QR Code endpoint — generate QR code PNG for share URLs."""

from __future__ import annotations

import asyncio
import io
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from core.config import settings
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/shares/{slug}/qr",
    tags=["Shares"],
    summary="Get QR code for a share",
    description="Generate a QR code PNG image for the share URL. Public, no auth required.",
)
async def get_share_qr(
    slug: str,
    size: int = Query(200, ge=50, le=1000, description="QR code image size in pixels"),
):
    """Generate a QR code PNG for the share's public URL."""
    # Verify share exists
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("shares")
        .select("slug")
        .eq("slug", slug)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Share not found")

    # Build the public URL
    share_url = f"{settings.frontend_url}/s/{slug}"

    # Generate QR code
    try:
        import qrcode
        from PIL import Image as PilImage
        from qrcode.constants import ERROR_CORRECT_M

        qr = qrcode.QRCode(
            version=None,  # auto-size
            error_correction=ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(share_url)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color="black", back_color="white")

        # Convert to PIL image and resize
        pil_img = qr_img.get_image()  # returns PIL Image
        if size != pil_img.size[0]:
            pil_img = pil_img.resize((size, size), PilImage.NEAREST)

        # Write to buffer
        buffer = io.BytesIO()
        pil_img.save(buffer, format="PNG")
        buffer.seek(0)

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="QR code generation not available (qrcode library not installed)",
        )
    except Exception as exc:
        logger.error("QR generation failed for slug=%s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Failed to generate QR code") from exc

    return StreamingResponse(
        buffer,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="{slug}-qr.png"',
            "Cache-Control": "public, max-age=86400",
        },
    )
