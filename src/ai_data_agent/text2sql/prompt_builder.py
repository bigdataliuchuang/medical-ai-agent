"""Prompt builder for Doris Text-to-SQL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ai_data_agent.graphrag.context_builder import TextToSqlContext


@dataclass(frozen=True)
class FewShotExample:
    """A question-SQL pair for few-shot prompting."""

    question: str
    sql: str
    domain: str
    tables: list[str]
    description: str = ""


def build_text_to_sql_prompt(context: TextToSqlContext) -> str:
    prompt_payload = context.to_prompt_dict()
    return "\n".join(
        [
            "你是生产级医疗数据治理平台的 Text-to-SQL 引擎。",
            "只输出一条 Doris SELECT SQL，不要输出解释、Markdown 或多余文本。",
            "必须使用下方 GraphRAG 上下文中的表、字段、指标口径、Join 路径和 DQ 约束。",
            "不得猜测不存在的表和字段。",
            "必须使用 schema-qualified 表名，例如 dws.dws_tumor_drug_usage_1d。",
            "当问题要求按科室、药品等业务对象展示，且上下文存在 *_name 维度时，优先输出名称字段，并可同时输出编码字段。",
            "不得生成 DROP、DELETE、UPDATE、INSERT、ALTER、TRUNCATE 或多语句 SQL。",
            "明细查询必须带 LIMIT。",
            "",
            "GraphRAG Context JSON:",
            json.dumps(prompt_payload, ensure_ascii=False, indent=2),
        ]
    )


def build_text_to_sql_prompt_with_few_shot(
    context: TextToSqlContext,
    examples: list[FewShotExample],
) -> str:
    """Build a prompt with few-shot examples for improved SQL generation."""
    prompt_payload = context.to_prompt_dict()
    parts = [
        "你是生产级医疗数据治理平台的 Text-to-SQL 引擎。",
        "只输出一条 Doris SELECT SQL，不要输出解释、Markdown 或多余文本。",
        "必须使用下方 GraphRAG 上下文中的表、字段、指标口径、Join 路径和 DQ 约束。",
        "不得猜测不存在的表和字段。",
        "必须使用 schema-qualified 表名，例如 dws.dws_tumor_drug_usage_1d。",
        "当问题要求按科室、药品等业务对象展示，且上下文存在 *_name 维度时，优先输出名称字段，并可同时输出编码字段。",
        "不得生成 DROP、DELETE、UPDATE、INSERT、ALTER、TRUNCATE 或多语句 SQL。",
        "明细查询必须带 LIMIT。",
    ]

    if examples:
        parts.append("")
        parts.append("以下是参考示例：")
        for i, ex in enumerate(examples, 1):
            parts.append(f"")
            parts.append(f"示例 {i}（{ex.domain}）：")
            parts.append(f"问题：{ex.question}")
            parts.append(f"SQL：{ex.sql}")

    parts.append("")
    parts.append("GraphRAG Context JSON:")
    parts.append(json.dumps(prompt_payload, ensure_ascii=False, indent=2))
    return "\n".join(parts)


def build_sql_repair_prompt(
    original_sql: str,
    error_reasons: list[str],
    context: TextToSqlContext,
) -> str:
    """Build a prompt asking the LLM to fix a rejected SQL query."""
    prompt_payload = context.to_prompt_dict()
    return "\n".join(
        [
            "你是生产级医疗数据治理平台的 Text-to-SQL 引擎。",
            "你之前生成的 SQL 被安全校验拒绝，请根据错误原因修复。",
            "",
            "原始 SQL：",
            original_sql,
            "",
            "校验失败原因：",
            *[f"- {reason}" for reason in error_reasons],
            "",
            "修复要求：",
            "- 只输出修复后的一条 Doris SELECT SQL",
            "- 不要输出解释、Markdown 或多余文本",
            "- 必须使用 schema-qualified 表名",
            "- 必须带 LIMIT",
            "- 不得生成 DDL/DML 语句",
            "",
            "GraphRAG Context JSON:",
            json.dumps(prompt_payload, ensure_ascii=False, indent=2),
        ]
    )
