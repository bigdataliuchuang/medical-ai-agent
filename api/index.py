from fastapi import APIRouter
from indexer.build_index import build_index

router = APIRouter()


@router.post("/api/index/rebuild")
def rebuild_index():
    build_index()
    return {"status": "ok", "message": "Schema index rebuilt successfully."}
