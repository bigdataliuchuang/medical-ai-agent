"""Tests for concrete tool implementations."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from ai_data_agent.agent.tool_impls import (
    AnalyzeResultTool,
    ExecuteSqlTool,
    GenerateSqlFromContextTool,
    SearchMetadataTool,
    ValidateSqlTool,
)
from ai_data_agent.agent.tools import ToolResult
from ai_data_agent.executor.doris import DorisExecutionError, DorisQueryResult
from ai_data_agent.graphrag.retriever import RetrievalContext
from ai_data_agent.text2sql.generator import SqlGenerationError, SqlGenerationResult
from ai_data_agent.text2sql.sql_guard import SqlGuardResult


def test_validate_sql_tool_passes():
    guard = MagicMock()
    guard.validate.return_value = SqlGuardResult(allowed=True, reasons=[], tables=["dws.t"])
    tool = ValidateSqlTool(guard)
    result = tool.execute({"sql": "SELECT * FROM dws.t LIMIT 10"})
    assert result.success is True
    data = json.loads(result.output)
    assert data["allowed"] is True


def test_validate_sql_tool_rejects():
    guard = MagicMock()
    guard.validate.return_value = SqlGuardResult(
        allowed=False,
        reasons=["SELECT * is not allowed."],
        tables=["dws.t"],
    )
    tool = ValidateSqlTool(guard)
    result = tool.execute({"sql": "SELECT * FROM dws.t LIMIT 10"})
    assert result.success is False
    data = json.loads(result.output)
    assert data["allowed"] is False
    assert "SELECT * is not allowed" in data["reasons"][0]


def test_execute_sql_tool_success():
    executor = MagicMock()
    executor.execute.return_value = DorisQueryResult(
        columns=["col_a", "col_b"],
        rows=[{"col_a": 1, "col_b": "x"}],
        row_count=1,
        elapsed_ms=42,
    )
    tool = ExecuteSqlTool(executor)
    result = tool.execute({"sql": "SELECT col_a, col_b FROM dws.t LIMIT 10"})
    assert result.success is True
    data = json.loads(result.output)
    assert data["columns"] == ["col_a", "col_b"]
    assert data["row_count"] == 1
    assert data["elapsed_ms"] == 42


def test_execute_sql_tool_failure():
    executor = MagicMock()
    executor.execute.side_effect = DorisExecutionError("Table not found")
    tool = ExecuteSqlTool(executor)
    result = tool.execute({"sql": "SELECT * FROM nonexistent LIMIT 10"})
    assert result.success is False
    assert "Table not found" in result.output


def test_generate_sql_from_context_tool_success():
    sql_gen = MagicMock()
    sql_gen.generate.return_value = SqlGenerationResult(
        sql="SELECT col FROM dws.t LIMIT 10",
        prompt="test prompt",
        raw_response="SELECT col FROM dws.t LIMIT 10",
        guard_result=SqlGuardResult(allowed=True, reasons=[], tables=["dws.t"]),
    )
    tool = GenerateSqlFromContextTool(sql_gen)
    context = MagicMock()
    result = tool.execute_with_context("test question", context)
    assert result.success is True
    data = json.loads(result.output)
    assert "SELECT" in data["sql"]


def test_generate_sql_from_context_tool_guard_rejects():
    sql_gen = MagicMock()
    sql_gen.generate.side_effect = SqlGenerationError("SELECT * is not allowed")
    tool = GenerateSqlFromContextTool(sql_gen)
    context = MagicMock()
    result = tool.execute_with_context("test question", context)
    assert result.success is False
    assert "SELECT * is not allowed" in result.output


def test_analyze_result_tool_with_context():
    analyzer = MagicMock()
    analysis = MagicMock()
    analysis.answer = "Drug usage is normal."
    analysis.downstream_suggestions = ["按科室下钻"]
    analyzer.analyze.return_value = analysis
    tool = AnalyzeResultTool(analyzer)
    query_result = DorisQueryResult(
        columns=["drug", "count"],
        rows=[{"drug": "A", "count": 100}],
        row_count=1,
        elapsed_ms=50,
    )
    context = MagicMock()
    result = tool.analyze_with_context("test question", "SELECT ...", query_result, context)
    assert result.success is True
    data = json.loads(result.output)
    assert data["answer"] == "Drug usage is normal."


def test_analyze_result_tool_execute_fallback_with_columns():
    """execute() fallback produces a meaningful summary when result_json is provided."""
    tool = AnalyzeResultTool(MagicMock())
    result_payload = json.dumps({
        "columns": ["drug_code", "total_amt"],
        "rows": [{"drug_code": "A001", "total_amt": 1234.5}],
        "row_count": 1,
    })
    result = tool.execute({
        "question": "药品用量",
        "sql": "SELECT drug_code, total_amt FROM ads.t LIMIT 10",
        "result_json": result_payload,
    })
    assert result.success is True
    data = json.loads(result.output)
    assert "1 行" in data["answer"]
    assert "drug_code" in data["answer"]
    assert len(data["downstream_suggestions"]) > 0


def test_analyze_result_tool_execute_fallback_empty_result():
    """execute() fallback handles empty result_json gracefully."""
    tool = AnalyzeResultTool(MagicMock())
    result = tool.execute({
        "question": "test",
        "sql": "SELECT 1",
        "result_json": "{}",
    })
    assert result.success is True
    data = json.loads(result.output)
    assert "0 行" in data["answer"]


def test_analyze_result_tool_execute_fallback_missing_result_json():
    """execute() fallback handles missing result_json key gracefully."""
    tool = AnalyzeResultTool(MagicMock())
    result = tool.execute({"question": "test", "sql": "SELECT 1"})
    assert result.success is True


def test_search_metadata_tool_success():
    retriever = MagicMock()
    retrieval = MagicMock(spec=RetrievalContext)
    retriever.search_metadata.return_value = retrieval

    context_builder = MagicMock()
    context = MagicMock()
    table = MagicMock()
    table.name = "dwd.dwd_patient"
    context.tables = [table]
    context.metrics = []
    context.dq_rules = []
    context.join_paths = []
    context.lineages = []
    context.sources = []
    context_builder.build.return_value = context

    tool = SearchMetadataTool(retriever, context_builder)
    result = tool.execute({"question": "test", "top_k": 3})
    assert result.success is True
    assert "context" in result.metadata


def test_search_metadata_tool_empty_tables_returns_failure():
    """When retrieval yields no tables, return failure so the agent knows context is insufficient."""
    retriever = MagicMock()
    retrieval = MagicMock(spec=RetrievalContext)
    retriever.search_metadata.return_value = retrieval

    context_builder = MagicMock()
    context = MagicMock()
    context.tables = []
    context.metrics = []
    context.dq_rules = []
    context.join_paths = []
    context.lineages = []
    context.sources = []
    context_builder.build.return_value = context

    tool = SearchMetadataTool(retriever, context_builder)
    result = tool.execute({"question": "test", "top_k": 3})
    assert result.success is False
    assert "no matching tables" in result.output.lower()
