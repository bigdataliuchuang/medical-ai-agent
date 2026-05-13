"""Semantic Layer service orchestration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ai_data_agent.semantic_service.audit import (
    InMemorySemanticAuditStore,
    SemanticAuditEvent,
)
from ai_data_agent.semantic_service.catalog import SemanticCatalog
from ai_data_agent.semantic_service.compiler import SemanticSqlCompiler
from ai_data_agent.semantic_service.dsl import SemanticCompileResponse, SemanticQueryRequest
from ai_data_agent.semantic_service.policy import PolicyEngine


class SemanticLayerService:
    def __init__(
        self,
        catalog: SemanticCatalog,
        query_executor: Any | None = None,
        audit_store: InMemorySemanticAuditStore | None = None,
    ):
        self.catalog = catalog
        self.policy = PolicyEngine(catalog)
        self.compiler = SemanticSqlCompiler(catalog)
        self.query_executor = query_executor
        self.audit_store = audit_store or InMemorySemanticAuditStore()

    def list_metrics(self) -> list[dict[str, Any]]:
        return [asdict(metric) for metric in self.catalog.list_metrics()]

    def list_dimensions(self) -> list[dict[str, Any]]:
        return [asdict(dimension) for dimension in self.catalog.list_dimensions()]

    def list_datasets(self) -> list[dict[str, Any]]:
        return [asdict(dataset) for dataset in self.catalog.list_datasets()]

    def compile_query(self, request: SemanticQueryRequest) -> SemanticCompileResponse:
        self.policy.authorize(request)
        compiled = self.compiler.compile(request)
        self.audit_store.append(
            SemanticAuditEvent.create(
                event_type="compile",
                tenant_id=request.tenant_id,
                role=request.role,
                status="success",
                message="Semantic query compiled.",
                payload=compiled.model_dump(),
            )
        )
        return compiled

    def execute_query(self, request: SemanticQueryRequest) -> dict[str, Any]:
        compiled = self.compile_query_without_audit(request)
        if self.query_executor is None:
            raise RuntimeError("Semantic query executor is not configured.")
        result = self.query_executor.execute(compiled.sql)
        payload = {
            "sql": compiled.sql,
            "dataset": compiled.dataset,
            "metrics": compiled.metrics,
            "dimensions": compiled.dimensions,
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "elapsed_ms": result.elapsed_ms,
        }
        self.audit_store.append(
            SemanticAuditEvent.create(
                event_type="query",
                tenant_id=request.tenant_id,
                role=request.role,
                status="success",
                message="Semantic query executed.",
                payload={"sql": compiled.sql, "row_count": result.row_count},
            )
        )
        return payload

    def compile_query_without_audit(
        self, request: SemanticQueryRequest
    ) -> SemanticCompileResponse:
        self.policy.authorize(request)
        return self.compiler.compile(request)

    def list_audit_events(self) -> list[dict[str, Any]]:
        return self.audit_store.list_events()
