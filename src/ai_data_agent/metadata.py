"""Metadata catalog loading for schema, metrics, DQ rules, and lineage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class MetadataError(RuntimeError):
    """Raised when metadata assets are missing or malformed."""


@dataclass(frozen=True)
class MetadataRepository:
    root: Path
    schema_catalog: dict[str, Any]
    metric_catalog: dict[str, Any]
    dq_rule_catalog: dict[str, Any]
    schema_graph: dict[str, Any]
    lineage_graph: dict[str, Any]

    @classmethod
    def load(cls, root: str | Path) -> "MetadataRepository":
        metadata_root = Path(root)
        return cls(
            root=metadata_root,
            schema_catalog=_load_yaml(metadata_root / "schema_catalog.yaml"),
            metric_catalog=_load_yaml(metadata_root / "metric_catalog.yaml"),
            dq_rule_catalog=_load_yaml(metadata_root / "dq_rule_catalog.yaml"),
            schema_graph=_load_yaml(metadata_root / "schema_graph.yaml"),
            lineage_graph=_load_yaml(metadata_root / "lineage_graph.yaml"),
        )

    def tables(self) -> list[dict[str, Any]]:
        return list(self.schema_catalog.get("tables", []))

    def metrics(self) -> list[dict[str, Any]]:
        return list(self.metric_catalog.get("metrics", []))

    def dq_rules(self) -> list[dict[str, Any]]:
        return list(self.dq_rule_catalog.get("rules", []))

    def find_table(self, name: str) -> dict[str, Any] | None:
        normalized = name.lower()
        return next((table for table in self.tables() if table.get("name", "").lower() == normalized), None)

    def find_metric(self, name: str) -> dict[str, Any] | None:
        normalized = name.lower()
        return next((metric for metric in self.metrics() if metric.get("name", "").lower() == normalized), None)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MetadataError(f"Metadata file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise MetadataError(f"Metadata file must contain a YAML mapping: {path}")
    return data
