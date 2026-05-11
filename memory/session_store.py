import os
import time
from dotenv import load_dotenv

load_dotenv()

MAX_TURNS = int(os.getenv("SESSION_MAX_TURNS", "10"))
TIMEOUT_MIN = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))

_store: dict = {}  # session_id -> {"messages": [...], "last_active": timestamp}


def get_history(session_id: str) -> list:
    _cleanup_expired()
    entry = _store.get(session_id)
    if not entry:
        return []
    return entry["messages"]


def add_message(session_id: str, role: str, content: str):
    _cleanup_expired()
    if session_id not in _store:
        _store[session_id] = {"messages": [], "last_active": time.time()}
    entry = _store[session_id]
    entry["messages"].append({"role": role, "content": content})
    entry["last_active"] = time.time()
    # 保留最近 N 轮（1轮=user+assistant）
    if len(entry["messages"]) > MAX_TURNS * 2:
        entry["messages"] = entry["messages"][-MAX_TURNS * 2:]


def clear_session(session_id: str):
    _store.pop(session_id, None)


def _cleanup_expired():
    now = time.time()
    expired = [sid for sid, entry in _store.items() if now - entry["last_active"] > TIMEOUT_MIN * 60]
    for sid in expired:
        del _store[sid]
