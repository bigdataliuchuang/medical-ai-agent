"""Compile Semantic Query DSL into guarded SQL."""

from __future__ import annotations

from typing import Any

from ai_data_agent.semantic_service.catalog import SemanticCatalog, SemanticCatalogError
from ai_data_agent.semantic_service.dsl import (
    SemanticCompileResponse,
    SemanticFilter,
    SemanticQueryRequest,
)


class SemanticCompileError(RuntimeError):
    """Raised when a semantic query cannot be compiled safely."""


class SemanticSqlCompiler:
    def __init__(self, catalog: SemanticCatalog):
        self.catalog = catalog

    def compile(self, request: SemanticQueryRequest) -> SemanticCompileResponse:
        metrics = [self.catalog.get_metric(name) for name in request.metrics]
        dataset_names = {metric.dataset for metric in metrics}
        if len(dataset_names) != 1:
            raise SemanticCompileError("Metrics from multiple datasets are not supported yet.")

        dataset_name = next(iter(dataset_names))
        dataset = self.catalog.get_dataset(dataset_name)
        dimensions = [self.catalog.get_dimension(name) for name in request.dimensions]
        for dimension in dimensions:
            if dimension.dataset != dataset_name:
                raise SemanticCompileError(
                    f"Dimension {dimension.name} does not belong to dataset {dataset_name}."
                )

        select_lines = [f"  {dimension.column}" for dimension in dimensions]
        select_lines.extend(f"  {metric.formula} AS {metric.name}" for metric in metrics)

        filters: list[SemanticFilter] = []
        for metric in metrics:
            filters.extend(metric.filters)
        filters.extend(request.filters)

        sql_lines = ["SELECT", ",\n".join(select_lines), f"FROM {dataset.table}"]
        if filters:
            where_lines = [_compile_filter(item) for item in filters]
            sql_lines.append("WHERE " + where_lines[0])
            sql_lines.extend(f"  AND {line}" for line in where_lines[1:])
        if dimensions:
            sql_lines.append(
                "GROUP BY " + ", ".join(dimension.column for dimension in dimensions)
            )
        sql_lines.append(f"LIMIT {request.limit}")
        return SemanticCompileResponse(
            sql="\n".join(sql_lines),
            dataset=dataset_name,
            metrics=[metric.name for metric in metrics],
            dimensions=[dimension.name for dimension in dimensions],
        )


def _compile_filter(filter_: SemanticFilter) -> str:
    field = _safe_identifier(filter_.field)
    if filter_.op == "eq":
        return f"{field} = {_literal(filter_.value)}"
    if filter_.op == "ne":
        return f"{field} <> {_literal(filter_.value)}"
    if filter_.op == "gt":
        return f"{field} > {_literal(filter_.value)}"
    if filter_.op == "gte":
        return f"{field} >= {_literal(filter_.value)}"
    if filter_.op == "lt":
        return f"{field} < {_literal(filter_.value)}"
    if filter_.op == "lte":
        return f"{field} <= {_literal(filter_.value)}"
    if filter_.op == "between":
        if not isinstance(filter_.value, list | tuple) or len(filter_.value) != 2:
            raise SemanticCompileError("between filter requires exactly two values.")
        return f"{field} BETWEEN {_literal(filter_.value[0])} AND {_literal(filter_.value[1])}"
    if filter_.op == "in":
        if not isinstance(filter_.value, list | tuple) or not filter_.value:
            raise SemanticCompileError("in filter requires a non-empty value list.")
        values = ", ".join(_literal(value) for value in filter_.value)
        return f"{field} IN ({values})"
    raise SemanticCompileError(f"Unsupported semantic filter operator: {filter_.op}")


def _safe_identifier(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise SemanticCompileError(f"Unsafe semantic field identifier: {value}")
    return value


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return str(value)
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"
