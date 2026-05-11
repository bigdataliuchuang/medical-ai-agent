# 查询审计日志 - 待实现（Phase 1）
import json, os
from datetime import datetime

def log(session_id: str, user_id: str, question: str, sql: str,
        status: str, row_count: int = 0, latency_ms: int = 0):
    os.makedirs("audit/logs", exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "user_id": user_id,
        "question": question,
        "generated_sql": sql,
        "execution_status": status,
        "row_count": row_count,
        "latency_ms": latency_ms,
    }
    with open(f"audit/logs/{date_str}.jsonl", "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
