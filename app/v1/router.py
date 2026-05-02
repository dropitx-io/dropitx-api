from fastapi import APIRouter

router = APIRouter()


@router.get("/documents")
async def list_documents():
    return {"message": "Phase 4 placeholder"}


@router.post("/documents")
async def create_document():
    return {"message": "Phase 4 placeholder"}
