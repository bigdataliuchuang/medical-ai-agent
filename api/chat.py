from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class ChatRequest(BaseModel):
    session_id: str
    message: str
    user_id: str = "anonymous"

@router.post("/api/chat")
def chat(req: ChatRequest):
    # 待实现（Phase 1）
    return {
        "answer": "功能建设中",
        "sql": "",
        "data": [],
        "row_count": 0,
        "status": "pending",
        "session_id": req.session_id,
    }

@router.get("/api/chat/history")
def history(session_id: str):
    return []
