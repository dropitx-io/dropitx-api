"""URLs of share pages. Share content is never addressed by a storage URL."""

from core.config import settings


def share_page_url(slug: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}/s/{slug}"
