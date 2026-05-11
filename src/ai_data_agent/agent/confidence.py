"""Confidence scoring for agent query results."""

from __future__ import annotations

from dataclasses import dataclass

from ai_data_agent.agent.loop import AgentTrace
from ai_data_agent.executor.doris import DorisQueryResult
from ai_data_agent.text2sql.sql_guard import SqlGuardResult


@dataclass(frozen=True)
class ConfidenceScore:
    """Multi-dimensional confidence assessment."""

    overall: float  # 0.0 - 1.0
    schema_confidence: float
    sql_validity: float
    execution_confidence: float
    explanation: str


class ConfidenceScorer:
    """Score agent results based on multiple quality signals."""

    def score(
        self,
        trace: AgentTrace,
        guard_result: SqlGuardResult | None = None,
        execution_result: DorisQueryResult | None = None,
        retrieval_score: float | None = None,
    ) -> ConfidenceScore:
        # Schema confidence: based on retrieval quality
        schema_conf = min(1.0, retrieval_score) if retrieval_score else 0.5

        # SQL validity: did guard pass? How many repairs needed?
        if guard_result is not None:
            sql_conf = 1.0 if guard_result.allowed else 0.2
        else:
            # Count repair steps
            repair_steps = sum(1 for s in trace.steps if s.action == "validate_sql" and s.observation and '"allowed":false' in s.observation)
            sql_conf = max(0.1, 1.0 - repair_steps * 0.3)

        # Execution confidence: did we get rows?
        if execution_result is not None:
            if execution_result.row_count > 0:
                exec_conf = 0.9
            else:
                exec_conf = 0.3
        else:
            exec_conf = 0.5

        # Agent confidence: did we reach a final answer without max_steps?
        agent_conf = 1.0 if trace.status == "success" else 0.2

        overall = schema_conf * 0.2 + sql_conf * 0.3 + exec_conf * 0.3 + agent_conf * 0.2

        explanation_parts = []
        if schema_conf < 0.5:
            explanation_parts.append("低检索质量")
        if sql_conf < 0.5:
            explanation_parts.append("SQL 校验有问题")
        if exec_conf < 0.5:
            explanation_parts.append("查询结果可能不完整")
        if agent_conf < 0.5:
            explanation_parts.append("Agent 未正常完成")
        explanation = "; ".join(explanation_parts) if explanation_parts else "查询质量良好"

        return ConfidenceScore(
            overall=round(overall, 3),
            schema_confidence=round(schema_conf, 3),
            sql_validity=round(sql_conf, 3),
            execution_confidence=round(exec_conf, 3),
            explanation=explanation,
        )
