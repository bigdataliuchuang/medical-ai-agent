"""Analyze Doris query results into business-facing answers."""

from __future__ import annotations

import json
from dataclasses import dataclass

from ai_data_agent.executor.doris import DorisQueryResult
from ai_data_agent.graphrag.context_builder import TextToSqlContext
from ai_data_agent.text2sql.llm import LlmClient


@dataclass(frozen=True)
class ResultAnalysis:
    answer: str
    downstream_suggestions: list[str]


class ResultAnalyzer:
    def __init__(self, llm: LlmClient):
        self.llm = llm

    def analyze(
        self,
        question: str,
        sql: str,
        query_result: DorisQueryResult,
        context: TextToSqlContext,
    ) -> ResultAnalysis:
        prompt = _build_analysis_prompt(question, sql, query_result, context)
        answer = self.llm.complete(prompt).strip()
        return ResultAnalysis(answer=answer, downstream_suggestions=_suggest_downstream_dimensions(context, answer))


def _build_analysis_prompt(
    question: str,
    sql: str,
    query_result: DorisQueryResult,
    context: TextToSqlContext,
) -> str:
    payload = {
        "question": question,
        "sql": sql,
        "columns": query_result.columns,
        "rows": query_result.rows[:50],
        "row_count": query_result.row_count,
        "metrics": [metric.__dict__ for metric in context.metrics],
        "tables": [table.__dict__ for table in context.tables],
    }
    return "\n".join(
        [
            "你是医疗数据治理平台的数据分析助手。",
            "只能基于真实 Doris 查询结果解释，不得编造未返回的数据。",
            "请输出简洁业务结论、异常原因假设和建议下钻方向。",
            "Input JSON:",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )


def _suggest_downstream_dimensions(context: TextToSqlContext, answer: str) -> list[str]:
    suggestions: list[str] = []
    dimensions = {
        dimension
        for metric in context.metrics
        for dimension in metric.dimensions
    }
    if "drug_code" in dimensions or "药品" in answer:
        suggestions.append("按药品下钻")
    if "dept_code" in dimensions or "科室" in answer:
        suggestions.append("按科室下钻")
    if "mpi_id" in dimensions or "患者" in answer:
        suggestions.append("按患者下钻")
    if not suggestions:
        suggestions.extend(["按科室下钻", "按药品下钻", "按患者下钻"])
    return suggestions
