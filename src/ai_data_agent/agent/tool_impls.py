"""Concrete tool implementations wrapping existing services."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ai_data_agent.agent.result_analyzer import ResultAnalyzer
from ai_data_agent.agent.tools import Tool, ToolResult
from ai_data_agent.executor.doris import DorisExecutionError, DorisExecutor, DorisQueryResult
from ai_data_agent.graphrag.context_builder import GraphRagContextBuilder, TextToSqlContext
from ai_data_agent.graphrag.retriever import GraphRagRetriever
from ai_data_agent.text2sql.generator import SqlGenerationError, SqlGenerationService
from ai_data_agent.text2sql.llm import ToolDefinition
from ai_data_agent.text2sql.sql_guard import SqlGuard

logger = logging.getLogger(__name__)


class SearchMetadataTool:
    """Search metadata catalog via GraphRAG retrieval."""

    def __init__(self, retriever: GraphRagRetriever, context_builder: GraphRagContextBuilder):
        self._retriever = retriever
        self._context_builder = context_builder

    @property
    def name(self) -> str:
        return "search_metadata"

    @property
    def description(self) -> str:
        return (
            "Search the medical data warehouse metadata catalog. "
            "Returns relevant tables, metrics, DQ rules, join paths, and lineage "
            "for the given natural language question."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The natural language question to search metadata for.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of vector search results.",
                    "default": 5,
                },
            },
            "required": ["question"],
        }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        question = arguments["question"]
        top_k = arguments.get("top_k", 5)
        try:
            retrieval = self._retriever.search_metadata(question, top_k=top_k)
            context = self._context_builder.build(retrieval)
            if not context.tables:
                logger.warning(
                    "GraphRAG retrieval returned 0 tables for question: %s", question[:80]
                )
                return ToolResult(
                    success=False,
                    output=(
                        "Metadata search returned no matching tables. "
                        "The question may be outside the current catalog scope. "
                        "Try rephrasing or check that the metadata index is populated."
                    ),
                )
            summary = {
                "tables": [t.name for t in context.tables],
                "metrics": [m.name for m in context.metrics],
                "dq_rules": [r.rule_code for r in context.dq_rules],
                "join_paths": len(context.join_paths),
                "lineages": len(context.lineages),
                "sources_count": len(context.sources),
            }
            return ToolResult(
                success=True,
                output=json.dumps(summary, ensure_ascii=False),
                metadata={"context": context},
            )
        except Exception as exc:
            logger.exception("GraphRAG retrieval failed for question: %s", question[:80])
            return ToolResult(success=False, output=f"Metadata search failed: {exc}")


class GenerateSqlFromContextTool:
    """Generate SQL using a pre-built TextToSqlContext."""

    def __init__(self, sql_generator: SqlGenerationService):
        self._generator = sql_generator

    @property
    def name(self) -> str:
        return "generate_sql"

    @property
    def description(self) -> str:
        return (
            "Generate a SQL query from a natural language question using the LLM. "
            "Must be called after search_metadata. The SQL is validated against safety rules."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The natural language question to generate SQL for.",
                },
            },
            "required": ["question"],
        }

    def execute_with_context(self, question: str, context: TextToSqlContext) -> ToolResult:
        try:
            result = self._generator.generate(context)
            return ToolResult(
                success=True,
                output=json.dumps({"sql": result.sql}, ensure_ascii=False),
                metadata={"sql": result.sql, "guard_result": result.guard_result},
            )
        except SqlGenerationError as exc:
            return ToolResult(
                success=False,
                output=f"SQL generation failed: {exc}",
            )
        except Exception as exc:
            return ToolResult(success=False, output=f"SQL generation error: {exc}")

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            success=False,
            output="generate_sql requires context from search_metadata. Call search_metadata first.",
        )


class ValidateSqlTool:
    """Validate SQL against safety rules without executing it."""

    def __init__(self, guard: SqlGuard):
        self._guard = guard

    @property
    def name(self) -> str:
        return "validate_sql"

    @property
    def description(self) -> str:
        return (
            "Validate a SQL query against safety rules (SELECT-only, schema-qualified, "
            "no SELECT *, must have LIMIT). Returns validation result with reasons."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL query to validate.",
                },
            },
            "required": ["sql"],
        }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        sql = arguments["sql"]
        try:
            result = self._guard.validate(sql)
            return ToolResult(
                success=result.allowed,
                output=json.dumps(
                    {
                        "allowed": result.allowed,
                        "reasons": result.reasons,
                        "tables": result.tables,
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            return ToolResult(success=False, output=f"SQL validation error: {exc}")


class ExecuteSqlTool:
    """Execute SQL against Doris and return results."""

    def __init__(self, executor: DorisExecutor, max_rows: int = 100):
        self._executor = executor
        self._max_rows = max_rows

    @property
    def name(self) -> str:
        return "execute_sql"

    @property
    def description(self) -> str:
        return (
            "Execute a validated SQL query against the Doris database. "
            "Returns columns, row count, and up to 100 sample rows."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL query to execute.",
                },
            },
            "required": ["sql"],
        }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        sql = arguments["sql"]
        try:
            result = self._executor.execute(sql)
            output = {
                "columns": result.columns,
                "row_count": result.row_count,
                "rows": result.rows[: self._max_rows],
                "elapsed_ms": result.elapsed_ms,
            }
            return ToolResult(
                success=True,
                output=json.dumps(output, ensure_ascii=False, default=str),
                metadata={"query_result": result},
            )
        except DorisExecutionError as exc:
            return ToolResult(success=False, output=f"SQL execution failed: {exc}")
        except Exception as exc:
            return ToolResult(success=False, output=f"Execution error: {exc}")


class AnalyzeResultTool:
    """Analyze query results into business insights."""

    def __init__(self, analyzer: ResultAnalyzer):
        self._analyzer = analyzer

    @property
    def name(self) -> str:
        return "analyze_result"

    @property
    def description(self) -> str:
        return (
            "Analyze SQL query results and produce a business-facing explanation "
            "with anomaly hypotheses and drill-down suggestions."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The original natural language question.",
                },
                "sql": {
                    "type": "string",
                    "description": "The executed SQL query.",
                },
                "result_json": {
                    "type": "string",
                    "description": "JSON string of the query result (columns, rows, row_count).",
                },
            },
            "required": ["question", "sql", "result_json"],
        }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        question = arguments.get("question", "")
        sql = arguments.get("sql", "")
        try:
            result_data = json.loads(arguments.get("result_json", "{}"))
            row_count = result_data.get("row_count", 0)
            columns = result_data.get("columns", [])
            rows = result_data.get("rows", [])
            summary = (
                f"查询返回 {row_count} 行，字段：{', '.join(columns)}。"
                if columns
                else f"查询返回 {row_count} 行。"
            )
            if rows:
                summary += f" 前 {min(3, len(rows))} 行样本：{rows[:3]}"
            return ToolResult(
                success=True,
                output=json.dumps(
                    {
                        "answer": summary,
                        "downstream_suggestions": ["按科室下钻", "按药品下钻", "按患者下钻"],
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            return ToolResult(success=False, output=f"Analysis error: {exc}")

    def analyze_with_context(
        self,
        question: str,
        sql: str,
        query_result: DorisQueryResult,
        context: TextToSqlContext,
    ) -> ToolResult:
        try:
            analysis = self._analyzer.analyze(question, sql, query_result, context)
            return ToolResult(
                success=True,
                output=json.dumps(
                    {
                        "answer": analysis.answer,
                        "downstream_suggestions": analysis.downstream_suggestions,
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            return ToolResult(success=False, output=f"Analysis error: {exc}")
