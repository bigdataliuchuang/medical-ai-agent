"""Build retrieval chunks from curated metadata assets."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable

from ai_data_agent.metadata import MetadataRepository


@dataclass(frozen=True)
class MetadataChunk:
    doc_id: str
    doc_type: str
    source_path: str
    layer: str | None
    business_domain: str | None
    table_name: str | None
    field_name: str | None
    metric_name: str | None
    content: str

    def metadata(self) -> dict[str, str]:
        return {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type,
            "source_path": self.source_path,
            "layer": self.layer or "",
            "business_domain": self.business_domain or "",
            "table_name": self.table_name or "",
            "field_name": self.field_name or "",
            "metric_name": self.metric_name or "",
        }


def build_metadata_chunks(repository: MetadataRepository) -> list[MetadataChunk]:
    chunks: list[MetadataChunk] = []
    chunks.extend(_table_chunks(repository.tables()))
    chunks.extend(_metric_chunks(repository.metrics()))
    chunks.extend(_dq_rule_chunks(repository.dq_rules()))
    chunks.extend(_schema_graph_chunks(repository.schema_graph.get("edges", [])))
    chunks.extend(_lineage_chunks(repository.lineage_graph.get("lineages", [])))
    return chunks


def _table_chunks(tables: Iterable[dict[str, Any]]) -> list[MetadataChunk]:
    chunks: list[MetadataChunk] = []
    for table in tables:
        table_name = table.get("name", "")
        source_path = _first_source_path(table)
        content = "\n".join(
            item
            for item in [
                f"表名: {table_name}",
                f"层级: {table.get('layer', '')}",
                f"业务域: {table.get('domain', '')}",
                f"说明: {table.get('description', '')}",
                "关键字段: " + ", ".join(table.get("key_fields", [])),
            ]
            if item.strip()
        )
        chunks.append(
            MetadataChunk(
                doc_id=_doc_id("table", table_name, content),
                doc_type="table",
                source_path=source_path,
                layer=table.get("layer"),
                business_domain=table.get("domain"),
                table_name=table_name,
                field_name=None,
                metric_name=None,
                content=content,
            )
        )
        for field in table.get("fields", []):
            field_name = field.get("name", "")
            field_content = f"表名: {table_name}\n字段: {field_name}\n字段说明: {field.get('description', '')}"
            chunks.append(
                MetadataChunk(
                    doc_id=_doc_id("field", table_name, field_name, field_content),
                    doc_type="field",
                    source_path=source_path,
                    layer=table.get("layer"),
                    business_domain=table.get("domain"),
                    table_name=table_name,
                    field_name=field_name,
                    metric_name=None,
                    content=field_content,
                )
            )
    return chunks


def _metric_chunks(metrics: Iterable[dict[str, Any]]) -> list[MetadataChunk]:
    chunks = []
    for metric in metrics:
        metric_name = metric.get("name", "")
        content = "\n".join(
            [
                f"指标: {metric.get('display_name', metric_name)}",
                f"指标编码: {metric_name}",
                f"说明: {metric.get('description', '')}",
                f"来源表: {metric.get('source_table', '')}",
                f"计算公式: {metric.get('formula', '')}",
                f"时间字段: {metric.get('time_field', '')}",
                "可用维度: " + ", ".join(metric.get("dimensions", [])),
                "过滤条件: " + "; ".join(metric.get("filters", [])),
            ]
        )
        chunks.append(
            MetadataChunk(
                doc_id=_doc_id("metric", metric_name, content),
                doc_type="metric",
                source_path="ai-data-agent/metadata/metric_catalog.yaml",
                layer=None,
                business_domain=None,
                table_name=metric.get("source_table"),
                field_name=None,
                metric_name=metric_name,
                content=content,
            )
        )
    return chunks


def _dq_rule_chunks(rules: Iterable[dict[str, Any]]) -> list[MetadataChunk]:
    chunks = []
    for rule in rules:
        rule_code = rule.get("rule_code", "")
        content = "\n".join(
            [
                f"DQ规则: {rule.get('name', rule_code)}",
                f"规则编码: {rule_code}",
                f"分类: {rule.get('category', '')}",
                f"严重等级: {rule.get('severity', '')}",
                f"层级: {rule.get('layer', '')}",
                "对象表: " + ", ".join(rule.get("target_tables", [])),
                "对象字段: " + ", ".join(rule.get("target_fields", [])),
                f"修复建议: {rule.get('fix_remark', '')}",
            ]
        )
        chunks.append(
            MetadataChunk(
                doc_id=_doc_id("dq_rule", rule_code, content),
                doc_type="dq_rule",
                source_path=_first_source_path(rule),
                layer=rule.get("layer"),
                business_domain="dq",
                table_name=",".join(rule.get("target_tables", [])),
                field_name=",".join(rule.get("target_fields", [])),
                metric_name=None,
                content=content,
            )
        )
    return chunks


def _schema_graph_chunks(edges: Iterable[dict[str, Any]]) -> list[MetadataChunk]:
    chunks = []
    for edge in edges:
        content = "\n".join(
            [
                f"关系类型: {edge.get('type', '')}",
                f"起点: {edge.get('from', '')}",
                f"终点: {edge.get('to', '')}",
                f"条件: {edge.get('on', '')}",
                f"说明: {edge.get('description', '')}",
            ]
        )
        chunks.append(
            MetadataChunk(
                doc_id=_doc_id("schema_graph", edge.get("from", ""), edge.get("to", ""), content),
                doc_type="schema_graph",
                source_path="ai-data-agent/metadata/schema_graph.yaml",
                layer=None,
                business_domain=None,
                table_name=f"{edge.get('from', '')},{edge.get('to', '')}",
                field_name=None,
                metric_name=None,
                content=content,
            )
        )
    return chunks


def _lineage_chunks(lineages: Iterable[dict[str, Any]]) -> list[MetadataChunk]:
    chunks = []
    for lineage in lineages:
        lineage_id = lineage.get("id", "")
        content = "\n".join(
            [
                f"血缘ID: {lineage_id}",
                f"说明: {lineage.get('description', '')}",
                "路径: " + " -> ".join(lineage.get("path", [])),
            ]
        )
        chunks.append(
            MetadataChunk(
                doc_id=_doc_id("lineage", lineage_id, content),
                doc_type="lineage",
                source_path="ai-data-agent/metadata/lineage_graph.yaml",
                layer=None,
                business_domain=None,
                table_name=",".join(lineage.get("path", [])),
                field_name=None,
                metric_name=None,
                content=content,
            )
        )
    return chunks


def _first_source_path(item: dict[str, Any]) -> str:
    paths = item.get("source_paths") or []
    return paths[0] if paths else ""


def _doc_id(*parts: str) -> str:
    raw = "|".join(parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"md-{digest}"
