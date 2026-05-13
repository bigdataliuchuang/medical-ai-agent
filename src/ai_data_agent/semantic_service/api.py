"""FastAPI routes for the platform Semantic Layer."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ai_data_agent.semantic_service.catalog import SemanticCatalogError
from ai_data_agent.semantic_service.compiler import SemanticCompileError
from ai_data_agent.semantic_service.dsl import SemanticQueryRequest
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
