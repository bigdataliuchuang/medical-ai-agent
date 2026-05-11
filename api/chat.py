import os
import random
import yaml
from fastapi import APIRouter
from pydantic import BaseModel
from agent import pipeline
from memory import session_store

router = APIRouter()

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema")


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


@router.get("/api/chat/suggestions")
def suggestions(count: int = 4):
    """返回随机推荐问题（从 schema sample_questions 抽取）"""
    all_questions = []
    if os.path.isdir(SCHEMA_DIR):
        for f in os.listdir(SCHEMA_DIR):
            if not f.endswith(".yaml"):
                continue
            with open(os.path.join(SCHEMA_DIR, f), encoding="utf-8") as fp:
                raw = yaml.safe_load(fp)
            for q in raw.get("sample_questions", []):
                all_questions.append(q)
    random.shuffle(all_questions)
    return {"suggestions": all_questions[:count]}
