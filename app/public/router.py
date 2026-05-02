from fastapi import APIRouter

router = APIRouter()


@router.get("/search")
async def search():
    return {"message": "Phase 3 placeholder"}


@router.post("/oembed")
async def oembed():
    return {"message": "Phase 3 placeholder"}
