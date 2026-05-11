"""YAML-backed schema and lineage graph retrieval."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GraphPath:
    nodes: list[str]
    edges: list[dict[str, Any]]


class SchemaGraphRetriever:
    def __init__(self, schema_graph: dict[str, Any], lineage_graph: dict[str, Any]):
        self.schema_graph = schema_graph
        self.lineage_graph = lineage_graph
        self.edges = list(schema_graph.get("edges", []))

    def find_join_path(self, start: str, end: str, max_depth: int = 5) -> GraphPath | None:
        adjacency: dict[str, list[dict[str, Any]]] = {}
        for edge in self.edges:
            if edge.get("type") != "join":
                continue
            adjacency.setdefault(edge["from"], []).append(edge)
            reverse = dict(edge)
            reverse["from"], reverse["to"] = edge["to"], edge["from"]
            adjacency.setdefault(reverse["from"], []).append(reverse)

        queue: deque[tuple[str, list[str], list[dict[str, Any]]]] = deque([(start, [start], [])])
        visited = {start}

        while queue:
            node, nodes, path_edges = queue.popleft()
            if node == end:
                return GraphPath(nodes=nodes, edges=path_edges)
            if len(path_edges) >= max_depth:
                continue
            for edge in adjacency.get(node, []):
                next_node = edge["to"]
                if next_node in visited:
                    continue
                visited.add(next_node)
                queue.append((next_node, nodes + [next_node], path_edges + [edge]))
        return None

    def find_lineage(self, table_or_metric: str) -> list[dict[str, Any]]:
        needle = table_or_metric.lower()
        matches = []
        for lineage in self.lineage_graph.get("lineages", []):
            path = [str(item).lower() for item in lineage.get("path", [])]
            if any(needle in item for item in path) or needle in str(lineage.get("id", "")).lower():
                matches.append(lineage)
        return matches

    def related_tables(self, table: str) -> list[str]:
        related: set[str] = set()
        for edge in self.edges:
            if edge.get("from") == table:
                related.add(edge.get("to", ""))
            if edge.get("to") == table:
                related.add(edge.get("from", ""))
        return sorted(item for item in related if item)
