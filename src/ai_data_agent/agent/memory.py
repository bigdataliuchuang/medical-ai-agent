"""Conversation memory backed by SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "data/conversation_memory.db"
_DEFAULT_TTL_S = 86400  # 24 hours
_MAX_HISTORY_TURNS = 5


@dataclass(frozen=True)
class ConversationTurn:
    session_id: str
    turn_number: int
    question: str
    answer: str
    sql: str | None = None
    tables_used: list[str] = field(default_factory=list)
    created_at: float = 0.0


class ConversationMemory:
    """SQLite-backed conversation history with TTL expiration."""

    def __init__(
        self,
        db_path: str | Path = _DEFAULT_DB_PATH,
        ttl_s: float = _DEFAULT_TTL_S,
    ):
        self._db_path = str(db_path)
        self._ttl_s = ttl_s
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    session_id   TEXT NOT NULL,
                    turn_number  INTEGER NOT NULL,
                    question     TEXT NOT NULL,
                    answer       TEXT NOT NULL,
                    sql_text     TEXT,
                    tables_used  TEXT,
                    created_at   REAL NOT NULL,
                    PRIMARY KEY (session_id, turn_number)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id)"
            )

    def get_history(
        self, session_id: str, max_turns: int = _MAX_HISTORY_TURNS
    ) -> list[ConversationTurn]:
        cutoff = time.time() - self._ttl_s
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, turn_number, question, answer, sql_text,
                       tables_used, created_at
                FROM conversation_turns
                WHERE session_id = ? AND created_at > ?
                ORDER BY turn_number DESC
                LIMIT ?
                """,
                (session_id, cutoff, max_turns),
            ).fetchall()
        turns = [
            ConversationTurn(
                session_id=r["session_id"],
                turn_number=r["turn_number"],
                question=r["question"],
                answer=r["answer"],
                sql=r["sql_text"],
                tables_used=json.loads(r["tables_used"]) if r["tables_used"] else [],
                created_at=r["created_at"],
            )
            for r in reversed(rows)  # chronological order
        ]
        return turns

    def save_turn(
        self,
        session_id: str,
        question: str,
        answer: str,
        sql: str | None = None,
        tables_used: list[str] | None = None,
    ) -> ConversationTurn:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(turn_number), 0) AS max_turn FROM conversation_turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            next_turn = row["max_turn"] + 1
            now = time.time()
            conn.execute(
                """
                INSERT INTO conversation_turns
                    (session_id, turn_number, question, answer, sql_text, tables_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    next_turn,
                    question,
                    answer,
                    sql,
                    json.dumps(tables_used or [], ensure_ascii=False),
                    now,
                ),
            )
        return ConversationTurn(
            session_id=session_id,
            turn_number=next_turn,
            question=question,
            answer=answer,
            sql=sql,
            tables_used=tables_used or [],
            created_at=now,
        )

    def clear_session(self, session_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM conversation_turns WHERE session_id = ?",
                (session_id,),
            )
            return cursor.rowcount

    def list_sessions(self) -> list[str]:
        cutoff = time.time() - self._ttl_s
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id
                FROM conversation_turns
                WHERE created_at > ?
                GROUP BY session_id
                ORDER BY MAX(created_at) DESC
                """,
                (cutoff,),
            ).fetchall()
        return [r["session_id"] for r in rows]

    def purge_expired(self) -> int:
        cutoff = time.time() - self._ttl_s
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM conversation_turns WHERE created_at <= ?",
                (cutoff,),
            )
            return cursor.rowcount
