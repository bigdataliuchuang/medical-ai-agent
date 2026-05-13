"""Semantic metadata catalog loading and lookup."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ai_data_agent.semantic_service.dsl import SemanticFilter


class SemanticCatalogError(RuntimeError):
    """Raised when semantic metadata is missing or inconsistent."""


@dataclass(frozen=True)
class SemanticDataset:
    name: str
    display_name: str
    table: str
    time_field: str
    fields: list[str]


@dataclass(frozen=True)
class SemanticDimension:
    name: str
    display_name: str
    dataset: str
    column: str
    data_type: str
    sensitivity: str = "public"
    hierarchy: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticMetric:
    name: str
    display_name: str
    description: str
    dataset: str
    formula: str
    dimensions: list[str]
    filters: list[SemanticFilter]
    version: str
    status: str
    owner: str
    approved_by: str | None = None
    lineage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticPolicy:
    tenant_id: str
    role: str
    allowed_metrics: list[str]
    allowed_dimensions: list[str]
    allow_sensitive_dimensions: bool = False


class SemanticCatalog:
    def __init__(
        self,
        datasets: list[SemanticDataset],
        dimensions: list[SemanticDimension],
        metrics: list[SemanticMetric],
        policies: list[SemanticPolicy],
    ):
        self.datasets = {item.name: item for item in datasets}
        self.dimensions = {item.name: item for item in dimensions}
        self.metrics = {item.name: item for item in metrics}
        self.policies = {(item.tenant_id, item.role): item for item in policies}

    @classmethod
    def load(cls, root: str | Path) -> "SemanticCatalog":
        metadata_root = Path(root)
        datasets = [
            SemanticDataset(
                name=str(item["name"]),
                display_name=str(item.get("display_name", item["name"])),
                table=str(item["table"]),
                time_field=str(item.get("time_field", "stat_date")),
                fields=[str(field) for field in item.get("fields", [])],
            )
            for item in _load_yaml(metadata_root / "datasets.yaml").get("datasets", [])
        ]
        dimensions = [
            SemanticDimension(
                name=str(item["name"]),
                display_name=str(item.get("display_name", item["name"])),
                dataset=str(item["dataset"]),
                column=str(item["column"]),
                data_type=str(item.get("data_type", "string")),
                sensitivity=str(item.get("sensitivity", "public")),
                hierarchy=[str(value) for value in item.get("hierarchy", [])],
            )
            for item in _load_yaml(metadata_root / "dimensions.yaml").get("dimensions", [])
        ]
        metrics = [
            SemanticMetric(
                name=str(item["name"]),
                display_name=str(item.get("display_name", item["name"])),
                description=str(item.get("description", "")),
                dataset=str(item["dataset"]),
                formula=str(item["formula"]),
                dimensions=[str(value) for value in item.get("dimensions", [])],
                filters=[SemanticFilter(**value) for value in item.get("filters", [])],
                version=str(item.get("version", "1.0.0")),
                status=str(item.get("status", "draft")),
                owner=str(item.get("owner", "")),
                approved_by=item.get("approved_by"),
                lineage=dict(item.get("lineage", {})),
            )
            for item in _load_yaml(metadata_root / "metrics.yaml").get("metrics", [])
        ]
        policies = [
            SemanticPolicy(
                tenant_id=str(item["tenant_id"]),
                role=str(item["role"]),
                allowed_metrics=[str(value) for value in item.get("allowed_metrics", [])],
                allowed_dimensions=[
                    str(value) for value in item.get("allowed_dimensions", [])
                ],
                allow_sensitive_dimensions=bool(
                    item.get("allow_sensitive_dimensions", False)
                ),
            )
            for item in _load_yaml(metadata_root / "policies.yaml").get("policies", [])
        ]
        catalog = cls(datasets, dimensions, metrics, policies)
        catalog.validate()
        return catalog

    def validate(self) -> None:
        for dimension in self.dimensions.values():
            if dimension.dataset not in self.datasets:
                raise SemanticCatalogError(
                    f"Dimension references unknown dataset: {dimension.name}"
                )
        for metric in self.metrics.values():
            if metric.dataset not in self.datasets:
                raise SemanticCatalogError(
                    f"Metric references unknown dataset: {metric.name}"
                )
            for dimension_name in metric.dimensions:
                if dimension_name not in self.dimensions:
                    raise SemanticCatalogError(
                        f"Metric references unknown dimension: {metric.name}.{dimension_name}"
                    )

    def get_dataset(self, name: str) -> SemanticDataset:
        try:
            return self.datasets[name]
        except KeyError as exc:
            raise SemanticCatalogError(f"Unknown dataset: {name}") from exc

    def get_dimension(self, name: str) -> SemanticDimension:
        try:
            return self.dimensions[name]
        except KeyError as exc:
            raise SemanticCatalogError(f"Unknown dimension: {name}") from exc

    def get_metric(self, name: str) -> SemanticMetric:
        try:
            return self.metrics[name]
        except KeyError as exc:
            raise SemanticCatalogError(f"Unknown metric: {name}") from exc

    def get_policy(self, tenant_id: str, role: str) -> SemanticPolicy:
        try:
            return self.policies[(tenant_id, role)]
        except KeyError as exc:
            raise SemanticCatalogError(
                f"Unknown semantic policy: tenant={tenant_id} role={role}"
            ) from exc

    def list_metrics(self) -> list[SemanticMetric]:
        return list(self.metrics.values())

    def list_dimensions(self) -> list[SemanticDimension]:
        return list(self.dimensions.values())

    def list_datasets(self) -> list[SemanticDataset]:
        return list(self.datasets.values())


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SemanticCatalogError(f"Semantic metadata file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise SemanticCatalogError(f"Semantic metadata must be a mapping: {path}")
    return loaded
