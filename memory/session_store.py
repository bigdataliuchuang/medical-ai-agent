import json
import os
import sqlite3
import time
import threading

DB_PATH = os.getenv("SESSION_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sessions.db"))
MAX_TURNS = int(os.getenv("SESSION_MAX_TURNS", "10"))
TIMEOUT_MIN = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))

_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                messages   TEXT NOT NULL DEFAULT '[]',
                last_active REAL NOT NULL
            )
        """)
        conn.commit()


_init_db()


def get_history(session_id: str) -> list:
    _cleanup_expired()
    with _lock, _get_conn() as conn:
        row = conn.execute(
            "SELECT messages FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    if not row:
        return []
    return json.loads(row["messages"])


def add_message(session_id: str, role: str, content: str):
    with _lock, _get_conn() as conn:
        row = conn.execute(
            "SELECT messages FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        messages = json.loads(row["messages"]) if row else []
        messages.append({"role": role, "content": content})
        # 保留最近 N 轮
        if len(messages) > MAX_TURNS * 2:
            messages = messages[-MAX_TURNS * 2:]
        conn.execute(
            """INSERT INTO sessions (session_id, messages, last_active)
               VALUES (?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                 messages = excluded.messages,
                 last_active = excluded.last_active""",
            (session_id, json.dumps(messages, ensure_ascii=False), time.time()),
        )
        conn.commit()


def clear_session(session_id: str):
    with _lock, _get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()


def _cleanup_expired():
    cutoff = time.time() - TIMEOUT_MIN * 60
    with _lock, _get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE last_active < ?", (cutoff,))
        conn.commit()
