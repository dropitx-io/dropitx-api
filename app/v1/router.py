"""V1 API router — aggregates all sub-routers under /api/v1."""

from fastapi import APIRouter

from app.v1.documents import router as documents_router
from app.v1.keys import router as keys_router

router = APIRouter()

router.include_router(documents_router)
router.include_router(keys_router)
