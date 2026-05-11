from fastapi import APIRouter
from pydantic import BaseModel
from agent import pipeline
from memory import session_store

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    message: str
    user_id: str = "anonymous"


@router.post("/api/chat")
def chat(req: ChatRequest):
    result = pipeline.run(
        question=req.message,
        session_id=req.session_id,
        user_id=req.user_id,
    )
    return result


@router.get("/api/chat/history")
def history(session_id: str):
    return session_store.get_history(session_id)
