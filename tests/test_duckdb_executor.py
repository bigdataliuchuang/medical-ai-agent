"""Tests for the local DuckDB executor."""

from __future__ import annotations

import sys
import types

import pytest

from ai_data_agent.executor.doris import DorisExecutionError


class FakeDuckDbRelation:
    def __init__(self, rows: list[tuple[object, ...]], columns: list[str]):
        self._rows = rows
        self.description = [(column,) for column in columns]

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class FakeDuckDbConnection:
    def __init__(self):
        self.executed: list[str] = []

    def execute(self, sql: str) -> FakeDuckDbRelation:
        self.executed.append(sql)
        return FakeDuckDbRelation(rows=[("肿瘤内科", 1280.5)], columns=["dept_name", "amount"])


def test_duckdb_executor_returns_query_result(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_connection = FakeDuckDbConnection()
    fake_duckdb = types.SimpleNamespace(connect=lambda path, read_only=False: fake_connection)
    monkeypatch.setitem(sys.modules, "duckdb", fake_duckdb)

    from ai_data_agent.executor.duckdb import DuckDBExecutor

    result = DuckDBExecutor(database_path="medical_dw.db").execute(
        "SELECT dept_name, amount FROM ads.ads_drug_usage_trend LIMIT 10"
    )

    assert fake_connection.executed == [
        "SELECT dept_name, amount FROM ads.ads_drug_usage_trend LIMIT 10"
    ]
    assert result.columns == ["dept_name", "amount"]
    assert result.rows == [{"dept_name": "肿瘤内科", "amount": 1280.5}]
    assert result.row_count == 1
    assert result.elapsed_ms >= 0


def test_duckdb_executor_wraps_runtime_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingConnection:
        def execute(self, sql: str) -> None:
            raise RuntimeError("bad sql")

    fake_duckdb = types.SimpleNamespace(connect=lambda path, read_only=False: FailingConnection())
    monkeypatch.setitem(sys.modules, "duckdb", fake_duckdb)

    from ai_data_agent.executor.duckdb import DuckDBExecutor

    with pytest.raises(DorisExecutionError, match="DuckDB query failed"):
        DuckDBExecutor(database_path="medical_dw.db").execute("SELECT bad")
