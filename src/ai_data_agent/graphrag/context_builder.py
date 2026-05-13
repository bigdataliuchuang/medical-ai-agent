"""Build structured GraphRAG context for Text-to-SQL."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from ai_data_agent.graphrag.graph import GraphPath, SchemaGraphRetriever
from ai_data_agent.graphrag.retriever import RetrievalContext
from ai_data_agent.metadata import MetadataRepository
from ai_data_agent.semantic_layer.metrics import MetricResolver


@dataclass(frozen=True)
class RetrievedSource:
    doc_id: str
    score: float
    doc_type: str
    source_path: str
    table_name: str
    field_name: str
    metric_name: str
    content: str


@dataclass(frozen=True)
class TableContext:
    name: str
    layer: str
    domain: str
    description: str
    key_fields: list[str]
    fields: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class MetricContext:
    name: str
    display_name: str
    description: str
    source_table: str
    formula: str
    time_field: str
    dimensions: list[str]
    filters: list[str]


@dataclass(frozen=True)
class DqRuleContext:
    rule_code: str
    name: str
    severity: str
    target_tables: list[str]
    target_fields: list[str]
    fix_remark: str


@dataclass(frozen=True)
class TextToSqlContext:
    question: str
    sources: list[RetrievedSource]
    tables: list[TableContext]
    metrics: list[MetricContext]
    dq_rules: list[DqRuleContext]
    join_paths: list[GraphPath]
    lineages: list[dict[str, Any]]

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "sources": [source.__dict__ for source in self.sources],
            "tables": [table.__dict__ for table in self.tables],
            "metrics": [metric.__dict__ for metric in self.metrics],
            "dq_rules": [rule.__dict__ for rule in self.dq_rules],
            "join_paths": [
                {
                    "nodes": path.nodes,
                    "conditions": [edge.get("on", "") for edge in path.edges],
                    "descriptions": [edge.get("description", "") for edge in path.edges],
                }
                for path in self.join_paths
            ],
            "lineages": self.lineages,
        }


class GraphRagContextBuilder:
    def __init__(
        self,
        repository: MetadataRepository,
        graph_retriever: SchemaGraphRetriever,
        metric_resolver: MetricResolver,
    ):
        self.repository = repository
        self.graph_retriever = graph_retriever
        self.metric_resolver = metric_resolver

    def build(self, retrieval: RetrievalContext) -> TextToSqlContext:
        sources = [_source_from_result(result) for result in retrieval.vector_results]
        table_names = _extract_table_names(sources)
        metric_names = _extract_metric_names(sources)

        tables = [
            _table_context(table)
            for table_name in table_names
            if (table := self.repository.find_table(table_name)) is not None
        ]

        metrics = []
        for metric_name in metric_names:
            metric = self.metric_resolver.resolve_by_name(metric_name)
            if metric is not None:
                metrics.append(_metric_context(metric))
        for metric in self.metric_resolver.search(retrieval.query):
            context = _metric_context(metric)
            if context.name not in {item.name for item in metrics}:
                metrics.append(context)

        dq_rules = [
            _dq_context(rule)
            for rule in self.repository.dq_rules()
            if _rule_matches_tables(rule, table_names) or _rule_matches_sources(rule, sources)
        ]

        join_paths = []
        for start, end in combinations(table_names, 2):
            path = self.graph_retriever.find_join_path(start, end)
            if path is not None and path not in join_paths:
                join_paths.append(path)

        lineages_by_id: dict[str, dict[str, Any]] = {}
        for lineage_list in retrieval.lineage_matches.values():
            for lineage in lineage_list:
                lineages_by_id[lineage.get("id", "")] = lineage
        for table_name in table_names:
            for lineage in self.graph_retriever.find_lineage(table_name):
                lineages_by_id[lineage.get("id", "")] = lineage
            for edge in self.repository.find_generated_lineage(table_name):
                edge_id = "generated:{source}->{target}:{file}".format(
                    source=edge.get("source_table", ""),
                    target=edge.get("target_table", ""),
                    file=edge.get("sql_file", ""),
                )
                lineages_by_id[edge_id] = edge

        return TextToSqlContext(
            question=retrieval.query,
            sources=sources,
            tables=tables,
            metrics=metrics,
            dq_rules=dq_rules,
            join_paths=join_paths,
            lineages=list(lineages_by_id.values()),
        )


def _source_from_result(result: Any) -> RetrievedSource:
    metadata = result.metadata
    return RetrievedSource(
        doc_id=result.doc_id,
        score=result.score,
        doc_type=metadata.get("doc_type", ""),
        source_path=metadata.get("source_path", ""),
        table_name=metadata.get("table_name", ""),
        field_name=metadata.get("field_name", ""),
        metric_name=metadata.get("metric_name", ""),
        content=result.content,
    )


def _extract_table_names(sources: list[RetrievedSource]) -> list[str]:
    names = {
        table.strip()
        for source in sources
        for table in source.table_name.split(",")
        if table.strip() and "." in table
    }
    return sorted(names)


def _extract_metric_names(sources: list[RetrievedSource]) -> list[str]:
    return sorted({source.metric_name for source in sources if source.metric_name})


def _table_context(table: dict[str, Any]) -> TableContext:
    return TableContext(
        name=table.get("name", ""),
        layer=table.get("layer", ""),
        domain=table.get("domain", ""),
        description=table.get("description", ""),
        key_fields=list(table.get("key_fields", [])),
        fields=[
            {
                "name": str(field.get("name", "")),
                "description": str(field.get("description", "")),
            }
            for field in table.get("fields", [])
        ],
    )


def _metric_context(metric: dict[str, Any]) -> MetricContext:
    return MetricContext(
        name=metric.get("name", ""),
        display_name=metric.get("display_name", ""),
        description=metric.get("description", ""),
        source_table=metric.get("source_table", ""),
        formula=metric.get("formula", ""),
        time_field=metric.get("time_field", ""),
        dimensions=list(metric.get("dimensions", [])),
        filters=list(metric.get("filters", [])),
    )


def _dq_context(rule: dict[str, Any]) -> DqRuleContext:
    return DqRuleContext(
        rule_code=rule.get("rule_code", ""),
        name=rule.get("name", ""),
        severity=rule.get("severity", ""),
        target_tables=list(rule.get("target_tables", [])),
        target_fields=list(rule.get("target_fields", [])),
        fix_remark=rule.get("fix_remark", ""),
    )


def _rule_matches_tables(rule: dict[str, Any], table_names: list[str]) -> bool:
    targets = set(rule.get("target_tables", []))
    return any(table in targets for table in table_names)


def _rule_matches_sources(rule: dict[str, Any], sources: list[RetrievedSource]) -> bool:
    rule_code = rule.get("rule_code", "")
    return any(rule_code and rule_code in source.content for source in sources)
