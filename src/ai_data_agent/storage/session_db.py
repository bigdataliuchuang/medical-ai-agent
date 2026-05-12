"""Session Storage: SQLite-backed observability for every agent execution."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_DB_PATH = "data/agent_runs.db"


@dataclass(frozen=True)
class ToolCallRecord:
    session_id: str
    request_id: str
    step_number: int
    tool_name: str
    tool_args: dict[str, Any]
    tool_result: str
    status: str  # "success" | "error"
    error_msg: str | None
    elapsed_ms: int
    start_time: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SqlAuditRecord:
    session_id: str
    request_id: str
    sql_text: str
    used_tables: list[str]
    has_sensitive_field: bool
    sensitive_fields: list[str]
    risk_level: str   # LOW | MEDIUM | HIGH
    check_result: str  # allowed | rejected
    reject_reason: str


@dataclass(frozen=True)
class EvalResultRecord:
    eval_run_id: str
    question_id: str
    question: str
    generated_sql: str
    expected_tables: list[str]
    actual_tables: list[str]
    table_match: bool
    sql_valid: bool
    sql_safe: bool
    elapsed_ms: int


class SessionDB:
    """SQLite store for complete agent execution observability.

    Five tables:
    - agent_session     : session lifecycle
    - agent_message     : user/assistant messages
    - agent_tool_call   : every tool invocation
    - agent_sql_audit   : SQL safety check results
    - agent_eval_result : offline evaluation run results
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        ddl = """
        CREATE TABLE IF NOT EXISTS agent_session (
            session_id  TEXT PRIMARY KEY,
            user_id     TEXT,
            started_at  REAL NOT NULL,
            last_active REAL NOT NULL,
            turn_count  INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS agent_message (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            request_id  TEXT NOT NULL,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_msg_session ON agent_message(session_id);

        CREATE TABLE IF NOT EXISTS agent_tool_call (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            request_id  TEXT NOT NULL,
            step_number INTEGER NOT NULL,
            tool_name   TEXT NOT NULL,
            tool_args   TEXT NOT NULL,
            tool_result TEXT NOT NULL,
            status      TEXT NOT NULL,
            error_msg   TEXT,
            start_time  REAL NOT NULL,
            elapsed_ms  INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_tool_session ON agent_tool_call(session_id);

        CREATE TABLE IF NOT EXISTS agent_sql_audit (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          TEXT NOT NULL,
            request_id          TEXT NOT NULL,
            sql_text            TEXT NOT NULL,
            used_tables         TEXT NOT NULL,
            has_sensitive_field INTEGER NOT NULL DEFAULT 0,
            sensitive_fields    TEXT NOT NULL DEFAULT '[]',
            risk_level          TEXT NOT NULL DEFAULT 'LOW',
            check_result        TEXT NOT NULL,
            reject_reason       TEXT,
            created_at          REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_audit_session ON agent_sql_audit(session_id);

        CREATE TABLE IF NOT EXISTS agent_eval_result (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            eval_run_id     TEXT NOT NULL,
            question_id     TEXT NOT NULL,
            question        TEXT NOT NULL,
            generated_sql   TEXT NOT NULL,
            expected_tables TEXT NOT NULL,
            actual_tables   TEXT NOT NULL,
            table_match     INTEGER NOT NULL DEFAULT 0,
            sql_valid       INTEGER NOT NULL DEFAULT 0,
            sql_safe        INTEGER NOT NULL DEFAULT 0,
            elapsed_ms      INTEGER NOT NULL DEFAULT 0,
            created_at      REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_eval_run ON agent_eval_result(eval_run_id);
        """
        with self._connect() as conn:
            conn.executescript(ddl)

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def create_session(self, session_id: str, user_id: str = "") -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_session
                    (session_id, user_id, started_at, last_active, turn_count)
                VALUES (?, ?, ?, ?, 0)
                """,
                (session_id, user_id, now, now),
            )

    def touch_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_session
                SET last_active = ?, turn_count = turn_count + 1
                WHERE session_id = ?
                """,
                (time.time(), session_id),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_session WHERE session_id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def log_message(
        self,
        session_id: str,
        request_id: str,
        role: str,
        content: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_message
                    (session_id, request_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, request_id, role, content, time.time()),
            )

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_message WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Tool calls
    # ------------------------------------------------------------------

    def log_tool_call(self, record: ToolCallRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_tool_call
                    (session_id, request_id, step_number, tool_name,
                     tool_args, tool_result, status, error_msg,
                     start_time, elapsed_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.session_id,
                    record.request_id,
                    record.step_number,
                    record.tool_name,
                    json.dumps(record.tool_args, ensure_ascii=False),
                    record.tool_result,
                    record.status,
                    record.error_msg,
                    record.start_time,
                    record.elapsed_ms,
                ),
            )

    def get_tool_calls(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_tool_call WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # SQL audit
    # ------------------------------------------------------------------

    def log_sql_audit(self, record: SqlAuditRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_sql_audit
                    (session_id, request_id, sql_text, used_tables,
                     has_sensitive_field, sensitive_fields, risk_level,
                     check_result, reject_reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.session_id,
                    record.request_id,
                    record.sql_text,
                    json.dumps(record.used_tables, ensure_ascii=False),
                    int(record.has_sensitive_field),
                    json.dumps(record.sensitive_fields, ensure_ascii=False),
                    record.risk_level,
                    record.check_result,
                    record.reject_reason,
                    time.time(),
                ),
            )

    def get_sql_audits(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_sql_audit WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_high_risk_audits(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_sql_audit
                WHERE risk_level = 'HIGH'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Eval results
    # ------------------------------------------------------------------

    def log_eval_result(self, record: EvalResultRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_eval_result
                    (eval_run_id, question_id, question, generated_sql,
                     expected_tables, actual_tables, table_match,
                     sql_valid, sql_safe, elapsed_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.eval_run_id,
                    record.question_id,
                    record.question,
                    record.generated_sql,
                    json.dumps(record.expected_tables, ensure_ascii=False),
                    json.dumps(record.actual_tables, ensure_ascii=False),
                    int(record.table_match),
                    int(record.sql_valid),
                    int(record.sql_safe),
                    record.elapsed_ms,
                    time.time(),
                ),
            )

    def get_eval_summary(self, eval_run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(sql_valid)   AS valid_cnt,
                    SUM(sql_safe)    AS safe_cnt,
                    SUM(table_match) AS match_cnt,
                    AVG(elapsed_ms)  AS avg_elapsed_ms
                FROM agent_eval_result
                WHERE eval_run_id = ?
                """,
                (eval_run_id,),
            ).fetchone()
        total = row["total"] or 0
        return {
            "eval_run_id": eval_run_id,
            "total": total,
            "sql_valid_rate": round(row["valid_cnt"] / total, 3) if total else 0.0,
            "sql_safe_rate": round(row["safe_cnt"] / total, 3) if total else 0.0,
            "table_match_rate": round(row["match_cnt"] / total, 3) if total else 0.0,
            "avg_elapsed_ms": round(row["avg_elapsed_ms"] or 0, 1),
        }
