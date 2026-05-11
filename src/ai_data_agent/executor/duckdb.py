"""Local DuckDB executor for pocket-mode development."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

from ai_data_agent.executor.doris import DorisExecutionError, DorisQueryResult


class DuckDBExecutor:
    """Execute validated SELECT statements against a local DuckDB database."""

    def __init__(self, database_path: str, read_only: bool = False):
        self.database_path = str(database_path)
        self.read_only = read_only

    def execute(self, sql: str) -> DorisQueryResult:
        try:
            import duckdb
        except ModuleNotFoundError as exc:
            raise DorisExecutionError(
                "duckdb is required for local pocket-mode execution. "
                "Install it with `pip install duckdb`."
            ) from exc

        started = time.monotonic()
        try:
            connection = duckdb.connect(self.database_path, read_only=self.read_only)
            try:
                cursor = connection.execute(sql)
                raw_rows = list(cursor.fetchall())
                columns = [str(desc[0]) for desc in cursor.description or []]
            finally:
                close = getattr(connection, "close", None)
                if callable(close):
                    close()
        except Exception as exc:
            raise DorisExecutionError(f"DuckDB query failed: {exc}") from exc

        rows = [_row_to_dict(row, columns) for row in raw_rows]
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return DorisQueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            elapsed_ms=elapsed_ms,
        )

    def ping(self) -> None:
        self.execute("SELECT 1")


def _row_to_dict(row: Any, columns: list[str]) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
        return {column: row[index] for index, column in enumerate(columns)}
    if len(columns) == 1:
        return {columns[0]: row}
    return {"value": row}
