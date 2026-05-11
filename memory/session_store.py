# 多轮对话历史 - 待实现（Phase 3）
_store: dict = {}

def get_history(session_id: str) -> list:
    return _store.get(session_id, [])

def add_message(session_id: str, role: str, content: str):
    if session_id not in _store:
        _store[session_id] = []
    _store[session_id].append({"role": role, "content": content})

def clear_session(session_id: str):
    _store.pop(session_id, None)
