"""QR Code generation endpoint (A5)."""

from __future__ import annotations

import asyncio
import io
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/qr/{slug}", tags=["Shares"])
async def get_qr_code(slug: str):
    """Generate a QR code PNG for a share URL. Returns image/png with cache headers."""
    # Verify share exists
    client = get_admin_client()
    try:
        resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("slug")
            .eq("slug", slug)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to verify slug for QR: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to generate QR code") from exc

    if not resp.data:
        raise HTTPException(status_code=404, detail="Share not found")

    # Build share URL
    from core.config import settings
    share_url = f"{settings.frontend_url}/s/{slug}"

    # Generate QR code
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(share_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        png_bytes = buf.getvalue()
    except ImportError:
        raise HTTPException(status_code=500, detail="QR code library not installed")
    except Exception as exc:
        logger.error("QR generation failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to generate QR code") from exc

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": f'inline; filename="qr-{slug}.png"',
        },
    )
