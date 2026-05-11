"""Metric resolution from the curated semantic layer."""

from __future__ import annotations

from typing import Any


class MetricResolver:
    def __init__(self, metric_catalog: dict[str, Any]):
        self.metrics = list(metric_catalog.get("metrics", []))

    def resolve_by_name(self, name: str) -> dict[str, Any] | None:
        normalized = name.lower()
        for metric in self.metrics:
            if metric.get("name", "").lower() == normalized:
                return metric
            if metric.get("display_name", "").lower() == normalized:
                return metric
        return None

    def search(self, text: str) -> list[dict[str, Any]]:
        normalized = text.lower()
        hits = []
        for metric in self.metrics:
            haystack = " ".join(
                str(metric.get(key, ""))
                for key in ("name", "display_name", "description", "source_table", "formula")
            ).lower()
            if normalized in haystack or any(token and token in haystack for token in normalized.split()):
                hits.append(metric)
        return hits
