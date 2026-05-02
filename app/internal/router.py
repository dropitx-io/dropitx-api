from fastapi import APIRouter

router = APIRouter()


@router.post("/publish")
async def publish():
    return {"message": "Phase 5 placeholder"}


@router.post("/upload")
async def upload():
    return {"message": "Phase 5 placeholder"}
