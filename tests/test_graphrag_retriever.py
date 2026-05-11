from __future__ import annotations

from pathlib import Path

from ai_data_agent.graphrag.graph import SchemaGraphRetriever
from ai_data_agent.graphrag.milvus_store import VectorSearchResult
from ai_data_agent.graphrag.retriever import GraphRagRetriever
from ai_data_agent.metadata import MetadataRepository


ROOT = Path(__file__).resolve().parents[1]


class StubEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class StubStore:
    def search(self, query_embedding: list[float], top_k: int = 5):
        return [
            VectorSearchResult(
                doc_id="md-test",
                score=0.98,
                content="抗肿瘤药物使用金额",
                metadata={
                    "doc_type": "metric",
                    "source_path": "ai-data-agent/metadata/metric_catalog.yaml",
                    "layer": "",
                    "business_domain": "drug",
                    "table_name": "dws.dws_tumor_drug_usage_1d",
                    "field_name": "",
                    "metric_name": "antitumor_drug_amount",
                },
            )
        ]


def test_retriever_combines_vector_hits_with_graph_context() -> None:
    repo = MetadataRepository.load(ROOT / "metadata")
    graph = SchemaGraphRetriever(repo.schema_graph, repo.lineage_graph)
    retriever = GraphRagRetriever(StubEmbeddingClient(), StubStore(), graph)

    context = retriever.search_metadata("肺癌患者抗肿瘤药物费用", top_k=1)

    assert context.vector_results[0].metadata["metric_name"] == "antitumor_drug_amount"
    assert "ads.ads_drug_usage_trend" in context.related_tables["dws.dws_tumor_drug_usage_1d"]
    assert "dws.dws_tumor_drug_usage_1d" in context.lineage_matches["dws.dws_tumor_drug_usage_1d"][0]["path"]
