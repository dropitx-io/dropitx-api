from fastapi import APIRouter

from app.internal.cli_upload import router as cli_upload_router
from app.internal.download import router as download_router
from app.internal.images import router as images_router
from app.internal.publish import router as publish_router
from app.internal.upload import router as upload_router
from app.internal.multi_upload import router as multi_upload_router
from app.internal.file_requests import router as file_requests_router

router = APIRouter()

router.include_router(publish_router)
router.include_router(upload_router)
router.include_router(multi_upload_router)
router.include_router(images_router)
router.include_router(download_router)
router.include_router(file_requests_router)
router.include_router(cli_upload_router)
