"""Doris executor skeleton.

This module intentionally does not provide a runtime fallback executor. Production
queries must use a real Doris FE connection after SQL Guard approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class DorisExecutionError(RuntimeError):
    """Raised when Doris execution fails."""


@dataclass(frozen=True)
class DorisQueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    elapsed_ms: int
    error_message: str | None = None


class DorisExecutor:
    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.database = database

    def execute(self, sql: str) -> DorisQueryResult:
        try:
            import pymysql
        except ModuleNotFoundError as exc:
            raise DorisExecutionError("pymysql is required for production Doris execution.") from exc

        import time

        started = time.monotonic()
        try:
            connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                cursorclass=pymysql.cursors.DictCursor,
            )
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                    rows = list(cursor.fetchall())
                    columns = [desc[0] for desc in cursor.description or []]
        except Exception as exc:
            raise DorisExecutionError(f"Doris query failed: {exc}") from exc

        elapsed_ms = int((time.monotonic() - started) * 1000)
        return DorisQueryResult(columns=columns, rows=rows, row_count=len(rows), elapsed_ms=elapsed_ms)

    def ping(self) -> None:
        try:
            import pymysql
        except ModuleNotFoundError as exc:
            raise DorisExecutionError("pymysql is required for production Doris health checks.") from exc

        try:
            connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                connect_timeout=5,
            )
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
        except Exception as exc:
            raise DorisExecutionError(f"Doris health check failed: {exc}") from exc
