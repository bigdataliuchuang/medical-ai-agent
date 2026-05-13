"""Semantic query DSL models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SemanticOperator = Literal["eq", "ne", "gt", "gte", "lt", "lte", "between", "in"]


class SemanticFilter(BaseModel):
    field: str
    op: SemanticOperator
    value: Any


class SemanticQueryRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    metrics: list[str] = Field(..., min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[SemanticFilter] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=1000)


class SemanticCompileResponse(BaseModel):
    sql: str
    dataset: str
    metrics: list[str]
    dimensions: list[str]


class MetricStatusUpdateRequest(BaseModel):
    status: Literal["draft", "published", "deprecated"]
    actor: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class MetricStatusApprovalRequest(BaseModel):
    metric_name: str = Field(..., min_length=1)
    requested_status: Literal["draft", "published", "deprecated"]
    requester: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class MetricStatusReviewRequest(BaseModel):
    reviewer: str = Field(..., min_length=1)
    comment: str = Field(..., min_length=1)
