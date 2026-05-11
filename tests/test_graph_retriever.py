from __future__ import annotations

from pathlib import Path

from ai_data_agent.graphrag.graph import SchemaGraphRetriever
from ai_data_agent.metadata import MetadataRepository


ROOT = Path(__file__).resolve().parents[1]


def test_find_join_path_between_diagnosis_and_drug_dict() -> None:
    repo = MetadataRepository.load(ROOT / "metadata")
    retriever = SchemaGraphRetriever(repo.schema_graph, repo.lineage_graph)

    path = retriever.find_join_path("dwd.dwd_diagnosis", "dim.dim_drug_dict")

    assert path is not None
    assert path.nodes == [
        "dwd.dwd_diagnosis",
        "dwd.dwd_visit",
        "dwd.dwd_order",
        "dim.dim_drug_dict",
    ]


def test_find_lineage_for_drug_usage_trend() -> None:
    repo = MetadataRepository.load(ROOT / "metadata")
    retriever = SchemaGraphRetriever(repo.schema_graph, repo.lineage_graph)

    lineages = retriever.find_lineage("ads.ads_drug_usage_trend")

    assert len(lineages) == 1
    assert "dws.dws_tumor_drug_usage_1d" in lineages[0]["path"]
