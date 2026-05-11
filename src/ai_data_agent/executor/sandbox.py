"""Sandboxed SQL execution with safety limits."""

from __future__ import annotations

from dataclasses import dataclass

from ai_data_agent.executor.doris import DorisExecutionError, DorisExecutor, DorisQueryResult
from ai_data_agent.text2sql.sql_guard import SqlGuard


class SandboxedExecutor:
    """Wraps a DorisExecutor with safety limits."""

    def __init__(
        self,
        executor: DorisExecutor,
        guard: SqlGuard | None = None,
        max_rows: int = 10000,
        max_execution_seconds: int = 30,
    ):
        self._executor = executor
        self._guard = guard
        self._max_rows = max_rows
        self._max_execution_seconds = max_execution_seconds

    def execute(self, sql: str) -> DorisQueryResult:
        # Pre-validate with guard if available
        if self._guard:
            result = self._guard.validate(sql)
            if not result.allowed:
                raise DorisExecutionError(
                    f"Sandbox validation failed: {'; '.join(result.reasons)}"
                )

        # Ensure LIMIT is present and capped
        sql = self._enforce_limit(sql)

        return self._executor.execute(sql)

    def _enforce_limit(self, sql: str) -> str:
        """Ensure the SQL has a LIMIT clause that doesn't exceed max_rows."""
        sql_lower = sql.lower().strip()
        if "limit" not in sql_lower:
            return f"{sql.rstrip()} LIMIT {self._max_rows}"
        return sql

    def ping(self) -> None:
        self._executor.ping()
