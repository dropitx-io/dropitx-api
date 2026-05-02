from fastapi import APIRouter

from app.internal.images import router as images_router
from app.internal.publish import router as publish_router
from app.internal.upload import router as upload_router

router = APIRouter()

router.include_router(publish_router)
router.include_router(upload_router)
router.include_router(images_router)
