"""Tenant and role policy checks for semantic queries."""

from __future__ import annotations

from ai_data_agent.semantic_service.catalog import SemanticCatalog
from ai_data_agent.semantic_service.dsl import SemanticQueryRequest


class PolicyViolation(PermissionError):
    """Raised when a semantic query violates tenant or role policy."""


class PolicyEngine:
    def __init__(self, catalog: SemanticCatalog):
        self.catalog = catalog

    def authorize(self, request: SemanticQueryRequest) -> None:
        policy = self.catalog.get_policy(request.tenant_id, request.role)
        for metric_name in request.metrics:
            if metric_name not in policy.allowed_metrics:
                raise PolicyViolation(
                    f"Role {request.role} is not allowed to access metric: {metric_name}"
                )
            self.catalog.get_metric(metric_name)

        for dimension_name in request.dimensions:
            if dimension_name not in policy.allowed_dimensions:
                raise PolicyViolation(
                    f"Role {request.role} is not allowed to access dimension: {dimension_name}"
                )
            dimension = self.catalog.get_dimension(dimension_name)
            if (
                dimension.sensitivity in {"restricted", "secret"}
                and not policy.allow_sensitive_dimensions
            ):
                raise PolicyViolation(
                    f"Role {request.role} is not allowed to access sensitive dimension: {dimension_name}"
                )
