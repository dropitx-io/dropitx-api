from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from app.v1.router import router as v1_router
from app.dashboard.router import router as dashboard_router
from app.public.router import router as public_router
from app.internal.router import router as internal_router

app = FastAPI(
    title="DropItX API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix="/api/v1", tags=["v1"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(public_router, prefix="/api", tags=["public"])
app.include_router(internal_router, prefix="/api", tags=["internal"])


@app.get("/health")
async def health_check():
    return {"status": "ok"}
