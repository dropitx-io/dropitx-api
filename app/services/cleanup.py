"""Background cleanup service for expired shares and old revisions."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

# How often to run cleanup (seconds)
CLEANUP_INTERVAL = 300  # 5 minutes


async def cleanup_expired_file_requests() -> int:
    """Delete file request uploads for expired requests.
    
    The file_requests row itself is kept (for history), but uploaded files
    in storage are removed to save space.
    Returns the number of uploads cleaned up.
    """
    client = get_admin_client()
    now = datetime.now(timezone.utc).isoformat()
    
    try:
        # Find expired requests that still have uploads
        resp = await asyncio.to_thread(
            lambda: client.table("file_requests")
            .select("id")
            .not_.is_("expires_at", "null")
            .lt("expires_at", now)
            .eq("is_active", True)
            .limit(50)
            .execute(),
        )
        rows = resp.data or []
    except Exception as exc:
        logger.error("Failed to query expired file requests: %s", exc)
        return 0
    
    if not rows:
        return 0
    
    deleted = 0
    for row in rows:
        try:
            # Deactivate the request
            await asyncio.to_thread(
                lambda rid=row["id"]: client.table("file_requests")
                .update({"is_active": False})
                .eq("id", rid)
                .execute(),
            )
            deleted += 1
            logger.info("Deactivated expired file request %s", row["id"])
        except Exception as exc:
            logger.error("Failed to deactivate file request %s: %s", row.get("id"), exc)
    
    return deleted


async def cleanup_expired_shares() -> int:
    """Delete shares that have passed their expires_at timestamp.

    Returns the number of shares deleted.
    """
    client = get_admin_client()
    now = datetime.now(timezone.utc).isoformat()

    try:
        resp = await asyncio.to_thread(
            lambda: client.table("shares")
            .select("*")
            .not_.is_("expires_at", "null")
            .lt("expires_at", now)
            .limit(100)
            .execute(),
        )
        rows = resp.data or []
    except Exception as exc:
        logger.error("Failed to query expired shares: %s", exc)
        return 0

    if not rows:
        return 0

    deleted = 0
    for row in rows:
        try:
            storage_path = row.get("storage_path")
            source = row.get("source", "")
            bucket = "html-files" if source in ("upload", "editor") else "shares"

            # Remove from storage
            if storage_path:
                try:
                    await asyncio.to_thread(
                        lambda sp=storage_path, b=bucket: client.storage.from_(b).remove([sp]),
                    )
                except Exception:
                    logger.warning("Failed to remove storage for expired share %s", row["id"])

            # Remove from DB
            await asyncio.to_thread(
                lambda rid=row["id"]: client.table("shares").delete().eq("id", rid).execute(),
            )
            deleted += 1
            logger.info("Deleted expired share %s (slug=%s)", row["id"], row.get("slug"))
        except Exception as exc:
            logger.error("Failed to delete expired share %s: %s", row.get("id"), exc)

    return deleted


async def cleanup_old_revisions(keep_per_share: int = 50) -> int:
    """Remove old revisions beyond the limit per share.

    Returns the number of revisions deleted.
    """
    client = get_admin_client()

    try:
        # Get all share_ids that have more than keep_per_share revisions
        resp = await asyncio.to_thread(
            lambda: client.table("share_revisions")
            .select("share_id")
            .execute(),
        )
        rows = resp.data or []
    except Exception as exc:
        logger.error("Failed to query revisions for cleanup: %s", exc)
        return 0

    if not rows:
        return 0

    # Group by share_id
    share_ids = list(set(r["share_id"] for r in rows))
    deleted = 0

    for share_id in share_ids:
        try:
            # Get revisions beyond the limit
            resp = await asyncio.to_thread(
                lambda sid=share_id: client.table("share_revisions")
                .select("id")
                .eq("share_id", sid)
                .order("revision", desc=True)
                .range(keep_per_share, keep_per_share + 999)
                .execute(),
            )
            old_rows = resp.data or []

            for old in old_rows:
                await asyncio.to_thread(
                    lambda rid=old["id"]: client.table("share_revisions")
                    .delete()
                    .eq("id", rid)
                    .execute(),
                )
                deleted += 1
        except Exception as exc:
            logger.error("Failed to cleanup revisions for share %s: %s", share_id, exc)

    if deleted:
        logger.info("Cleaned up %d old revisions", deleted)
    return deleted


async def run_cleanup_loop() -> None:
    """Background loop that periodically cleans up expired shares and old revisions."""
    logger.info("Starting cleanup service (interval=%ds)", CLEANUP_INTERVAL)
    while True:
        try:
            expired = await cleanup_expired_shares()
            if expired:
                logger.info("Cleanup: deleted %d expired shares", expired)

            revisions = await cleanup_old_revisions()
            if revisions:
                logger.info("Cleanup: deleted %d old revisions", revisions)

            file_requests = await cleanup_expired_file_requests()
            if file_requests:
                logger.info("Cleanup: deactivated %d expired file requests", file_requests)
        except Exception as exc:
            logger.error("Cleanup loop error: %s", exc, exc_info=True)

        await asyncio.sleep(CLEANUP_INTERVAL)
