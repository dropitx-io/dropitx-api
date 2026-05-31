from fastapi import APIRouter

from app.public.shares import router as shares_router
from app.public.search import router as search_router
from app.public.analytics import router as analytics_router
from app.public.oembed import router as oembed_router
from app.public.qrcode import router as qrcode_router
from app.public.comments import router as comments_router
from app.public.versions import router as versions_router
from app.public.encryption import router as encryption_router
from app.public.preview import router as preview_router
from app.public.file_requests import router as file_requests_public_router
from app.public.explore import router as explore_router
from app.public.stars import router as stars_router
from app.public.profiles import router as profiles_router
from app.public.languages import router as languages_router

router = APIRouter()

router.include_router(explore_router)
router.include_router(stars_router)
router.include_router(profiles_router)
router.include_router(shares_router)
router.include_router(search_router)
router.include_router(analytics_router)
router.include_router(oembed_router)
router.include_router(qrcode_router)
router.include_router(comments_router, prefix="/shares")
router.include_router(versions_router)
router.include_router(encryption_router)
router.include_router(preview_router)
router.include_router(file_requests_public_router)
router.include_router(languages_router)
