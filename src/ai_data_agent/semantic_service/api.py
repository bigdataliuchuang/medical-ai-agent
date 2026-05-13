"""FastAPI routes for the platform Semantic Layer."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ai_data_agent.semantic_service.catalog import SemanticCatalogError
from ai_data_agent.semantic_service.compiler import SemanticCompileError
from ai_data_agent.semantic_service.dsl import (
    MetricStatusApprovalRequest,
    MetricStatusReviewRequest,
    MetricStatusUpdateRequest,
    SemanticQueryRequest,
)
from ai_data_agent.semantic_service.governance import SemanticGovernanceError
from ai_data_agent.semantic_service.policy import PolicyViolation
from ai_data_agent.semantic_service.service import SemanticLayerService

router = APIRouter(prefix="/api/v1/semantic", tags=["semantic-layer"])


def get_semantic_service(request: Request) -> SemanticLayerService:
    return request.app.state.semantic_service


@router.get("/metrics")
async def list_metrics(service: SemanticLayerService = Depends(get_semantic_service)):
    return {"items": service.list_metrics()}


@router.get("/dimensions")
async def list_dimensions(service: SemanticLayerService = Depends(get_semantic_service)):
    return {"items": service.list_dimensions()}


@router.get("/datasets")
async def list_datasets(service: SemanticLayerService = Depends(get_semantic_service)):
    return {"items": service.list_datasets()}


@router.post("/compile")
async def compile_query(
    request: SemanticQueryRequest,
    service: SemanticLayerService = Depends(get_semantic_service),
):
    try:
        return service.compile_query(request)
    except PolicyViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (SemanticCatalogError, SemanticCompileError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/query")
async def execute_query(
    request: SemanticQueryRequest,
    service: SemanticLayerService = Depends(get_semantic_service),
):
    try:
        return service.execute_query(request)
    except PolicyViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (SemanticCatalogError, SemanticCompileError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/audit/events")
async def list_audit_events(
    service: SemanticLayerService = Depends(get_semantic_service),
):
    return {"items": service.list_audit_events()}


@router.post("/governance/metrics/{metric_name}/status")
async def update_metric_status(
    metric_name: str,
    request: MetricStatusUpdateRequest,
    service: SemanticLayerService = Depends(get_semantic_service),
):
    try:
        return service.update_metric_status(
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
async def request_metric_status_change(
    request: MetricStatusApprovalRequest,
    service: SemanticLayerService = Depends(get_semantic_service),
):
    try:
        return service.request_metric_status_change(
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
async def list_metric_status_requests(
    service: SemanticLayerService = Depends(get_semantic_service),
):
    return {"items": service.list_metric_status_requests()}


@router.post("/governance/metric-status-requests/{request_id}/approve")
async def approve_metric_status_request(
    request_id: str,
    request: MetricStatusReviewRequest,
    service: SemanticLayerService = Depends(get_semantic_service),
):
    try:
        return service.approve_metric_status_request(
            request_id=request_id,
            reviewer=request.reviewer,
            comment=request.comment,
        )
    except SemanticGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/governance/metric-status-requests/{request_id}/reject")
async def reject_metric_status_request(
    request_id: str,
    request: MetricStatusReviewRequest,
    service: SemanticLayerService = Depends(get_semantic_service),
):
    try:
        return service.reject_metric_status_request(
            request_id=request_id,
            reviewer=request.reviewer,
            comment=request.comment,
        )
    except SemanticGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
