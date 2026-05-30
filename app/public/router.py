from fastapi import APIRouter

from app.public.shares import router as shares_router
from app.public.search import router as search_router
from app.public.analytics import router as analytics_router
from app.public.oembed import router as oembed_router
from app.public.qrcode import router as qrcode_router
from app.public.comments import router as comments_router
from app.public.versions import router as versions_router

router = APIRouter()

router.include_router(shares_router)
router.include_router(search_router)
router.include_router(analytics_router)
router.include_router(oembed_router)
router.include_router(qrcode_router)
router.include_router(comments_router)
router.include_router(versions_router)
