"""Tests for executor.doris module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_data_agent.executor.doris import (
    DorisExecutionError,
    DorisExecutor,
    DorisQueryResult,
)


class TestDorisQueryResult:
    def test_frozen_dataclass(self):
        result = DorisQueryResult(
            columns=["a", "b"],
            rows=[{"a": 1, "b": 2}],
            row_count=1,
            elapsed_ms=10,
        )
        assert result.columns == ["a", "b"]
        assert result.row_count == 1
        assert result.elapsed_ms == 10
        assert result.error_message is None

    def test_with_error_message(self):
        result = DorisQueryResult(
            columns=[],
            rows=[],
            row_count=0,
            elapsed_ms=0,
            error_message="something broke",
        )
        assert result.error_message == "something broke"

    def test_immutable(self):
        result = DorisQueryResult(columns=[], rows=[], row_count=0, elapsed_ms=0)
        with pytest.raises(AttributeError):
            result.row_count = 5  # type: ignore[misc]


class TestDorisExecutor:
    def test_constructor_coerces_port(self):
        executor = DorisExecutor("host", "9030", "user", "pass", "db")  # type: ignore[arg-type]
        assert executor.port == 9030
        assert isinstance(executor.port, int)

    @patch("ai_data_agent.executor.doris.pymysql", create=True)
    def test_execute_success(self, mock_pymysql_module):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"cnt": 42}]
        mock_cursor.description = [("cnt", None)]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"pymysql": mock_pymysql_module}):
            mock_pymysql_module.connect.return_value = mock_conn
            mock_pymysql_module.cursors = MagicMock()
            mock_pymysql_module.cursors.DictCursor = MagicMock()

            executor = DorisExecutor("localhost", 9030, "root", "", "test_db")
            result = executor.execute("SELECT COUNT(*) AS cnt FROM t")

        assert isinstance(result, DorisQueryResult)
        assert result.columns == ["cnt"]
        assert result.rows == [{"cnt": 42}]
        assert result.row_count == 1
        assert result.elapsed_ms >= 0

    @patch("ai_data_agent.executor.doris.pymysql", create=True)
    def test_execute_connection_failure(self, mock_pymysql_module):
        with patch.dict("sys.modules", {"pymysql": mock_pymysql_module}):
            mock_pymysql_module.connect.side_effect = ConnectionError("refused")
            mock_pymysql_module.cursors = MagicMock()

            executor = DorisExecutor("bad-host", 9030, "root", "", "db")
            with pytest.raises(DorisExecutionError, match="Doris query failed"):
                executor.execute("SELECT 1")

    @patch("ai_data_agent.executor.doris.pymysql", create=True)
    def test_execute_query_failure(self, mock_pymysql_module):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = RuntimeError("syntax error")

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"pymysql": mock_pymysql_module}):
            mock_pymysql_module.connect.return_value = mock_conn
            mock_pymysql_module.cursors = MagicMock()
            mock_pymysql_module.cursors.DictCursor = MagicMock()

            executor = DorisExecutor("localhost", 9030, "root", "", "db")
            with pytest.raises(DorisExecutionError, match="Doris query failed"):
                executor.execute("INVALID SQL")

    @patch("ai_data_agent.executor.doris.pymysql", create=True)
    def test_ping_success(self, mock_pymysql_module):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"pymysql": mock_pymysql_module}):
            mock_pymysql_module.connect.return_value = mock_conn
            mock_pymysql_module.cursors = MagicMock()

            executor = DorisExecutor("localhost", 9030, "root", "", "db")
            executor.ping()  # should not raise

    @patch("ai_data_agent.executor.doris.pymysql", create=True)
    def test_ping_failure(self, mock_pymysql_module):
        with patch.dict("sys.modules", {"pymysql": mock_pymysql_module}):
            mock_pymysql_module.connect.side_effect = ConnectionError("timeout")
            mock_pymysql_module.cursors = MagicMock()

            executor = DorisExecutor("bad-host", 9030, "root", "", "db")
            with pytest.raises(DorisExecutionError, match="Doris health check failed"):
                executor.ping()

    def test_execute_without_pymysql(self):
        """When pymysql is not installed, execute raises DorisExecutionError."""
        import sys

        saved = sys.modules.get("pymysql")
        sys.modules["pymysql"] = None  # type: ignore[assignment]
        try:
            executor = DorisExecutor("localhost", 9030, "root", "", "db")
            with pytest.raises(DorisExecutionError, match="pymysql is required"):
                executor.execute("SELECT 1")
        finally:
            if saved is not None:
                sys.modules["pymysql"] = saved
            else:
                sys.modules.pop("pymysql", None)

    def test_ping_without_pymysql(self):
        """When pymysql is not installed, ping raises DorisExecutionError."""
        import sys

        saved = sys.modules.get("pymysql")
        sys.modules["pymysql"] = None  # type: ignore[assignment]
        try:
            executor = DorisExecutor("localhost", 9030, "root", "", "db")
            with pytest.raises(DorisExecutionError, match="pymysql is required"):
                executor.ping()
        finally:
            if saved is not None:
                sys.modules["pymysql"] = saved
            else:
                sys.modules.pop("pymysql", None)
