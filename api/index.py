from fastapi import APIRouter, BackgroundTasks
from indexer.build_index import build_index

router = APIRouter()


@router.post("/api/index/rebuild")
def rebuild_index(background_tasks: BackgroundTasks):
    background_tasks.add_task(build_index)
    return {"status": "accepted", "message": "Index rebuild started in background."}
