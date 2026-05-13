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
from ai_data_agent.semantic_service.governance import SQLiteSemanticGovernanceStore
from ai_data_agent.semantic_service.policy import PolicyEngine


class SemanticLayerService:
    def __init__(
        self,
        catalog: SemanticCatalog,
        query_executor: Any | None = None,
        audit_store: InMemorySemanticAuditStore | None = None,
        governance_store: SQLiteSemanticGovernanceStore | None = None,
    ):
        self.catalog = catalog
        self.policy = PolicyEngine(catalog)
        self.compiler = SemanticSqlCompiler(catalog)
        self.query_executor = query_executor
        self.audit_store = audit_store or InMemorySemanticAuditStore()
        self.governance_store = governance_store

    def list_metrics(self) -> list[dict[str, Any]]:
        metrics = [asdict(metric) for metric in self.catalog.list_metrics()]
        if self.governance_store is None:
            return metrics
        overrides = self.governance_store.get_metric_statuses()
        for metric in metrics:
            override = overrides.get(metric["name"])
            if override is not None:
                metric["status"] = override.status
                metric["status_actor"] = override.actor
                metric["status_reason"] = override.reason
                metric["status_updated_at"] = override.updated_at
        return metrics

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

    def update_metric_status(
        self,
        metric_name: str,
        status: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        self.catalog.get_metric(metric_name)
        if self.governance_store is None:
            raise RuntimeError("Semantic governance store is not configured.")
        override = self.governance_store.set_metric_status(
            metric_name=metric_name,
            status=status,
            actor=actor,
            reason=reason,
        )
        self.audit_store.append(
            SemanticAuditEvent.create(
                event_type="metric_status_change",
                tenant_id="system",
                role="semantic-governance",
                status="success",
                message=f"Metric {metric_name} status changed to {status}.",
                payload=asdict(override),
            )
        )
        return {
            "name": override.metric_name,
            "status": override.status,
            "actor": override.actor,
            "reason": override.reason,
            "updated_at": override.updated_at,
        }

    def request_metric_status_change(
        self,
        metric_name: str,
        requested_status: str,
        requester: str,
        reason: str,
    ) -> dict[str, Any]:
        self.catalog.get_metric(metric_name)
        if self.governance_store is None:
            raise RuntimeError("Semantic governance store is not configured.")
        request = self.governance_store.create_metric_status_request(
            metric_name=metric_name,
            requested_status=requested_status,
            requester=requester,
            reason=reason,
        )
        payload = asdict(request)
        self.audit_store.append(
            SemanticAuditEvent.create(
                event_type="metric_status_request",
                tenant_id="system",
                role="semantic-governance",
                status="pending",
                message=f"Metric {metric_name} status change requested.",
                payload=payload,
            )
        )
        return payload

    def list_metric_status_requests(self) -> list[dict[str, Any]]:
        if self.governance_store is None:
            return []
        return [asdict(item) for item in self.governance_store.list_metric_status_requests()]

    def approve_metric_status_request(
        self,
        request_id: str,
        reviewer: str,
        comment: str,
    ) -> dict[str, Any]:
        return self._review_metric_status_request(
            request_id=request_id,
            decision="approved",
            reviewer=reviewer,
            comment=comment,
        )

    def reject_metric_status_request(
        self,
        request_id: str,
        reviewer: str,
        comment: str,
    ) -> dict[str, Any]:
        return self._review_metric_status_request(
            request_id=request_id,
            decision="rejected",
            reviewer=reviewer,
            comment=comment,
        )

    def _review_metric_status_request(
        self,
        request_id: str,
        decision: str,
        reviewer: str,
        comment: str,
    ) -> dict[str, Any]:
        if self.governance_store is None:
            raise RuntimeError("Semantic governance store is not configured.")
        reviewed = self.governance_store.review_metric_status_request(
            request_id=request_id,
            decision=decision,
            reviewer=reviewer,
            comment=comment,
        )
        if decision == "approved":
            self.governance_store.set_metric_status(
                metric_name=reviewed.metric_name,
                status=reviewed.requested_status,
                actor=reviewer,
                reason=comment,
            )
        payload = asdict(reviewed)
        self.audit_store.append(
            SemanticAuditEvent.create(
                event_type=f"metric_status_{decision}",
                tenant_id="system",
                role="semantic-governance",
                status=decision,
                message=f"Metric status request {request_id} {decision}.",
                payload=payload,
            )
        )
        return payload
