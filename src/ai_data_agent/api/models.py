"""Pydantic request and response models for the Data Agent API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户自然语言问题")
    top_k: int = Field(default=5, ge=1, le=20, description="Milvus 检索条数")
    max_rows: int = Field(default=100, ge=1, le=1000, description="Doris 返回最大行数")


class ContextSummary(BaseModel):
    tables: list[str] = Field(default_factory=list, description="命中的表名")
    metrics: list[str] = Field(default_factory=list, description="命中的指标")
    dq_rules: list[str] = Field(default_factory=list, description="命中的 DQ 规则")
    join_paths: int = Field(default=0, description="Join 路径数")
    sources_count: int = Field(default=0, description="向量检索命中数")


class QueryResponse(BaseModel):
    request_id: str
    question: str
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    elapsed_ms: int
    answer: str
    downstream_suggestions: list[str] = Field(default_factory=list)
    context_summary: ContextSummary


class AgentStepResponse(BaseModel):
    step_number: int
    thought: str | None = None
    action: str | None = None
    action_input: dict[str, Any] | None = None
    observation: str | None = None
    is_final: bool = False
    elapsed_ms: int = 0


class AgentQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户自然语言问题")
    session_id: str | None = Field(default=None, description="会话 ID，不传则新建")
    max_steps: int = Field(default=8, ge=1, le=20, description="Agent 最大推理步数")
    max_rows: int = Field(default=100, ge=1, le=1000, description="Doris 返回最大行数")


class AgentQueryResponse(BaseModel):
    request_id: str
    session_id: str
    question: str
    sql: str | None = None
    answer: str | None = None
    status: str  # "success" | "max_steps" | "error"
    steps: list[AgentStepResponse] = Field(default_factory=list)
    total_elapsed_ms: int = 0
    total_llm_calls: int = 0


class ConversationTurnResponse(BaseModel):
    turn_number: int
    question: str
    answer: str
    sql: str | None = None
    tables_used: list[str] = Field(default_factory=list)
    created_at: float = 0.0


class SessionHistoryResponse(BaseModel):
    session_id: str
    turns: list[ConversationTurnResponse] = Field(default_factory=list)


class SessionDeleteResponse(BaseModel):
    session_id: str
    deleted_turns: int


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)
