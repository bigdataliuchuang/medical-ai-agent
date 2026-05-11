from __future__ import annotations

from pathlib import Path

from ai_data_agent.graphrag.context_builder import GraphRagContextBuilder
from ai_data_agent.graphrag.graph import SchemaGraphRetriever
from ai_data_agent.graphrag.milvus_store import VectorSearchResult
from ai_data_agent.graphrag.retriever import RetrievalContext
from ai_data_agent.metadata import MetadataRepository
from ai_data_agent.semantic_layer.metrics import MetricResolver


ROOT = Path(__file__).resolve().parents[1]


def test_context_builder_outputs_text_to_sql_context() -> None:
    repo = MetadataRepository.load(ROOT / "metadata")
    graph = SchemaGraphRetriever(repo.schema_graph, repo.lineage_graph)
    builder = GraphRagContextBuilder(repo, graph, MetricResolver(repo.metric_catalog))

    retrieval = RetrievalContext(
        query="统计本月肺癌患者抗肿瘤药物费用",
        vector_results=[
            VectorSearchResult(
                doc_id="metric-1",
                score=0.99,
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
            ),
            VectorSearchResult(
                doc_id="table-1",
                score=0.95,
                content="诊断清洗明细表",
                metadata={
                    "doc_type": "table",
                    "source_path": "ai-data-agent/metadata/schema_catalog.yaml",
                    "layer": "DWD",
                    "business_domain": "diagnosis",
                    "table_name": "dwd.dwd_diagnosis",
                    "field_name": "",
                    "metric_name": "",
                },
            ),
        ],
        related_tables={
            "dws.dws_tumor_drug_usage_1d": ["ads.ads_drug_usage_trend"],
            "dwd.dwd_diagnosis": ["dwd.dwd_visit"],
        },
        lineage_matches={
            "dws.dws_tumor_drug_usage_1d": [
                {
                    "id": "inpatient_order_to_drug_usage",
                    "path": [
                        "ods.ods_inpatient_order",
                        "dwd.dwd_order",
                        "dws.dws_tumor_drug_usage_1d",
                        "ads.ads_drug_usage_trend",
                    ],
                }
            ]
        },
    )

    context = builder.build(retrieval)
    prompt_dict = context.to_prompt_dict()

    assert prompt_dict["question"] == "统计本月肺癌患者抗肿瘤药物费用"
    assert any(metric["name"] == "antitumor_drug_amount" for metric in prompt_dict["metrics"])
    assert any(table["name"] == "dwd.dwd_diagnosis" for table in prompt_dict["tables"])
    assert all("fields" in table for table in prompt_dict["tables"])
    assert any("dws.dws_tumor_drug_usage_1d" in lineage["path"] for lineage in prompt_dict["lineages"])
    assert prompt_dict["sources"][0]["source_path"] == "ai-data-agent/metadata/metric_catalog.yaml"
