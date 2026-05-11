import json
import os
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "audit", "logs")


def log(session_id: str, user_id: str, question: str, sql: str,
        status: str, row_count: int = 0, latency_ms: int = 0,
        intent: str = "", retrieved_tables: list = None,
        guard_result: str = "", answer: str = ""):
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "user_id": user_id,
        "question": question,
        "intent": intent,
        "retrieved_tables": retrieved_tables or [],
        "generated_sql": sql,
        "guard_result": guard_result,
        "execution_status": status,
        "row_count": row_count,
        "latency_ms": latency_ms,
        "answer_length": len(answer),
    }
    with open(os.path.join(LOG_DIR, f"{date_str}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_logs(date_str: str = None, user_id: str = None, page: int = 1, page_size: int = 20) -> dict:
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(LOG_DIR, f"{date_str}.jsonl")
    if not os.path.exists(path):
        return {"logs": [], "total": 0, "page": page, "page_size": page_size}

    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if user_id and entry.get("user_id") != user_id:
                continue
            entries.append(entry)

    total = len(entries)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "logs": entries[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
