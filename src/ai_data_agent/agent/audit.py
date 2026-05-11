"""Audit logging contracts for Data Agent query lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


class AuditLogError(RuntimeError):
    """Raised when audit logging fails."""


@dataclass(frozen=True)
class AuditRecord:
    request_id: str
    question: str
    sql: str
    status: str
    retrieved_sources: int
    context_tables: list[str]
    context_metrics: list[str]
    context_dq_rules: list[str]
    row_count: int
    elapsed_ms: int
    error_message: str | None
    answer_summary: str | None
    created_at: str = ""

    def with_timestamp(self) -> "AuditRecord":
        if self.created_at:
            return self
        return AuditRecord(
            request_id=self.request_id,
            question=self.question,
            sql=self.sql,
            status=self.status,
            retrieved_sources=self.retrieved_sources,
            context_tables=self.context_tables,
            context_metrics=self.context_metrics,
            context_dq_rules=self.context_dq_rules,
            row_count=self.row_count,
            elapsed_ms=self.elapsed_ms,
            error_message=self.error_message,
            answer_summary=self.answer_summary,
            created_at=datetime.now(timezone.utc).isoformat(),
        )


class AuditLogger(Protocol):
    def write(self, record: AuditRecord) -> None:
        """Persist one audit record."""


class NoopAuditLogger:
    """Audit logger used by local pocket mode when no audit sink is configured."""

    def write(self, record: AuditRecord) -> None:
        record.with_timestamp()


class DorisAuditLogger:
    """Persist audit records to Doris.

    This logger requires a real Doris connection. It is intentionally separate
    from the query executor so audit failures can be handled explicitly by the
    API layer without pretending audit succeeded.
    """

    def __init__(self, host: str, port: int, user: str, password: str, database: str, table: str):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.database = database
        self.table = table

    def write(self, record: AuditRecord) -> None:
        try:
            import pymysql
        except ModuleNotFoundError as exc:
            raise AuditLogError("pymysql is required for Doris audit logging.") from exc

        record = record.with_timestamp()
        sql = f"""
INSERT INTO {self.table}
(request_id, question, sql_text, status, retrieved_sources, context_tables,
 context_metrics, context_dq_rules, row_count, elapsed_ms, error_message,
 answer_summary, created_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
        values = (
            record.request_id,
            record.question,
            record.sql,
            record.status,
            record.retrieved_sources,
            ",".join(record.context_tables),
            ",".join(record.context_metrics),
            ",".join(record.context_dq_rules),
            record.row_count,
            record.elapsed_ms,
            record.error_message,
            record.answer_summary,
            record.created_at,
        )
        try:
            connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
            )
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql, values)
                connection.commit()
        except Exception as exc:
            raise AuditLogError(f"Doris audit write failed: {exc}") from exc


@dataclass(frozen=True)
class AgentStepRecord:
    """A single step in an agent trace for audit purposes."""

    step_number: int
    thought: str | None
    tool_name: str | None
    tool_input: dict[str, Any] | None
    tool_output: str | None
    tool_success: bool
    elapsed_ms: int


@dataclass(frozen=True)
class AgentTraceRecord:
    """Complete agent trace for audit persistence."""

    request_id: str
    question: str
    steps: list[AgentStepRecord]
    final_sql: str | None
    final_answer: str | None
    status: str
    total_elapsed_ms: int
    total_llm_calls: int
    total_llm_tokens: int = 0
    created_at: str = ""

    def with_timestamp(self) -> "AgentTraceRecord":
        if self.created_at:
            return self
        return AgentTraceRecord(
            request_id=self.request_id,
            question=self.question,
            steps=self.steps,
            final_sql=self.final_sql,
            final_answer=self.final_answer,
            status=self.status,
            total_elapsed_ms=self.total_elapsed_ms,
            total_llm_calls=self.total_llm_calls,
            total_llm_tokens=self.total_llm_tokens,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
