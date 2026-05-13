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
from ai_data_agent.semantic_service.dsl import SemanticQueryRequest
from ai_data_agent.semantic_service.policy import PolicyViolation
from ai_data_agent.semantic_service.audit import SQLiteSemanticAuditStore
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
