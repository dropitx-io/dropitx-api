from fastapi import APIRouter

router = APIRouter()


@router.get("/teams")
async def list_teams():
    return {"message": "Phase 6 placeholder"}
