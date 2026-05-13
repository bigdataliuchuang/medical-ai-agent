import os
import sys
from types import SimpleNamespace
from pathlib import Path

from fastapi import APIRouter, HTTPException

from agent.executor import execute

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_data_agent.semantic_service.catalog import SemanticCatalog, SemanticCatalogError
from ai_data_agent.semantic_service.compiler import SemanticCompileError
from ai_data_agent.semantic_service.dsl import (
    MetricStatusApprovalRequest,
    MetricStatusReviewRequest,
    MetricStatusUpdateRequest,
    SemanticQueryRequest,
)
from ai_data_agent.semantic_service.policy import PolicyViolation
from ai_data_agent.semantic_service.audit import SQLiteSemanticAuditStore
from ai_data_agent.semantic_service.governance import SemanticGovernanceError, SQLiteSemanticGovernanceStore
from ai_data_agent.semantic_service.service import SemanticLayerService

router = APIRouter(prefix="/api/v1/semantic", tags=["semantic-layer"])


class LegacyDorisExecutor:
    def execute(self, sql: str):
        result = execute(sql)
        if result.get("error"):
            raise RuntimeError(result["error"])
        rows = result.get("data", [])
        columns = list(rows[0].keys()) if rows else []
        return SimpleNamespace(
            columns=columns,
            rows=rows,
            row_count=result.get("row_count", len(rows)),
            elapsed_ms=0,
        )


semantic_service = SemanticLayerService(
    SemanticCatalog.load("metadata/semantic"),
    query_executor=LegacyDorisExecutor(),
    audit_store=SQLiteSemanticAuditStore(os.getenv("SEMANTIC_AUDIT_DB_PATH", "data/semantic_audit.db")),
    governance_store=SQLiteSemanticGovernanceStore(os.getenv("SEMANTIC_AUDIT_DB_PATH", "data/semantic_audit.db")),
)


@router.get("/metrics")
async def list_metrics():
    return {"items": semantic_service.list_metrics()}


@router.get("/dimensions")
async def list_dimensions():
    return {"items": semantic_service.list_dimensions()}


@router.get("/datasets")
async def list_datasets():
    return {"items": semantic_service.list_datasets()}


@router.post("/compile")
async def compile_query(request: SemanticQueryRequest):
    try:
        return semantic_service.compile_query(request)
    except PolicyViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (SemanticCatalogError, SemanticCompileError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/query")
async def execute_query(request: SemanticQueryRequest):
    try:
        return semantic_service.execute_query(request)
    except PolicyViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (SemanticCatalogError, SemanticCompileError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/audit/events")
async def list_audit_events():
    return {"items": semantic_service.list_audit_events()}


@router.post("/governance/metrics/{metric_name}/status")
async def update_metric_status(metric_name: str, request: MetricStatusUpdateRequest):
    try:
        return semantic_service.update_metric_status(
            metric_name=metric_name,
            status=request.status,
            actor=request.actor,
            reason=request.reason,
        )
    except SemanticCatalogError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SemanticGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/governance/metric-status-requests")
async def request_metric_status_change(request: MetricStatusApprovalRequest):
    try:
        return semantic_service.request_metric_status_change(
            metric_name=request.metric_name,
            requested_status=request.requested_status,
            requester=request.requester,
            reason=request.reason,
        )
    except SemanticCatalogError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SemanticGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/governance/metric-status-requests")
async def list_metric_status_requests():
    return {"items": semantic_service.list_metric_status_requests()}


@router.post("/governance/metric-status-requests/{request_id}/approve")
async def approve_metric_status_request(request_id: str, request: MetricStatusReviewRequest):
    try:
        return semantic_service.approve_metric_status_request(
            request_id=request_id,
            reviewer=request.reviewer,
            comment=request.comment,
        )
    except SemanticGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/governance/metric-status-requests/{request_id}/reject")
async def reject_metric_status_request(request_id: str, request: MetricStatusReviewRequest):
    try:
        return semantic_service.reject_metric_status_request(
            request_id=request_id,
            reviewer=request.reviewer,
            comment=request.comment,
        )
    except SemanticGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
